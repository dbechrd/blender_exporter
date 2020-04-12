# =============================================================
#
#  Open Game Engine Exchange
#  http://opengex.org/
#
#  Export plugin for Blender
#  by Eric Lengyel
#
#  Version 2.0
#
#  Copyright 2017, Terathon Software LLC
#
#  This software is licensed under the Creative Commons
#  Attribution-ShareAlike 3.0 Unported License:
#
#  http://creativecommons.org/licenses/by-sa/3.0/deed.en_US
#
# =============================================================

bl_info = {
    "name": "OpenGEX format (.ogex)",
    "description": "Terathon Software OpenGEX Exporter",
    "author": "Eric Lengyel",
    "version": (2, 0, 0, 0),
    'blender': (2, 80, 0),
    "location": "File > Import-Export",
    "wiki_url": "http://opengex.org/",
    "category": "Import-Export"}

import bpy
import math
import re
import struct
import typing
from bpy_extras.io_utils import ExportHelper

kNodeTypeNode = 0
kNodeTypeBone = 1
kNodeTypeGeometry = 2
kNodeTypeLight = 3
kNodeTypeCamera = 4

kAnimationSampled = 0
kAnimationLinear = 1
kAnimationBezier = 2

kExportEpsilon = 1.0e-6

structIdentifier = [B"Node $", B"BoneNode $", B"GeometryNode $", B"LightNode $", B"CameraNode $"]

subtranslationName = [B"xpos", B"ypos", B"zpos"]
subrotationName = [B"xrot", B"yrot", B"zrot"]
subscaleName = [B"xscl", B"yscl", B"zscl"]
deltaSubtranslationName = [B"dxpos", B"dypos", B"dzpos"]
deltaSubrotationName = [B"dxrot", B"dyrot", B"dzrot"]
deltaSubscaleName = [B"dxscl", B"dyscl", B"dzscl"]
axisName = [B"x", B"y", B"z"]

class ExportVertex:
    __slots__ = ("hash", "vertexIndex", "faceIndex", "position", "normal", "color", "texcoord0", "texcoord1")

    def __init__(self):
        self.color = [1.0, 1.0, 1.0]
        self.texcoord0 = [0.0, 0.0]
        self.texcoord1 = [0.0, 0.0]

    def __eq__(self, v):
        if (self.hash != v.hash):
            return (False)
        if (self.position != v.position):
            return (False)
        if (self.normal != v.normal):
            return (False)
        if (self.color != v.color):
            return (False)
        if (self.texcoord0 != v.texcoord0):
            return (False)
        if (self.texcoord1 != v.texcoord1):
            return (False)
        return (True)

    def Hash(self):
        h = hash(self.position[0])
        h = h * 21737 + hash(self.position[1])
        h = h * 21737 + hash(self.position[2])
        h = h * 21737 + hash(self.normal[0])
        h = h * 21737 + hash(self.normal[1])
        h = h * 21737 + hash(self.normal[2])
        h = h * 21737 + hash(self.color[0])
        h = h * 21737 + hash(self.color[1])
        h = h * 21737 + hash(self.color[2])
        h = h * 21737 + hash(self.texcoord0[0])
        h = h * 21737 + hash(self.texcoord0[1])
        h = h * 21737 + hash(self.texcoord1[0])
        h = h * 21737 + hash(self.texcoord1[1])
        self.hash = h

    # TODO: Why are we rolling our own hash function above? Is it faster/better somehow? Profile it!
    #def Hash(self):
    #    h = hash(
    #        self.position[0],
    #        self.position[1],
    #        self.position[2],
    #        self.normal[0],
    #        self.normal[1],
    #        self.normal[2],
    #        self.color[0],
    #        self.color[1],
    #        self.color[2],
    #        self.texcoord0[0],
    #        self.texcoord0[1],
    #        self.texcoord1[0],
    #        self.texcoord1[1]
    #    )
    #    self.hash = h

class OpenGexExporter(bpy.types.Operator, ExportHelper):
    """Export to OpenGEX format"""
    bl_idname = "export_scene.ogex"
    bl_label = "Export OpenGEX"
    filename_ext = ".ogex"

    option_export_selection = bpy.props.BoolProperty(name = "Export Selection Only", description = "Export only selected objects", default = False)
    option_sample_animation = bpy.props.BoolProperty(name = "Force Sampled Animation", description = "Always export animation as per-frame samples", default = False)

    def Write(self, text):
        self.file.write(text)

    def IndentWrite(self, text, extra = 0, newline = False):
        if (newline):
            self.file.write(B"\n")
        for i in range(self.indentLevel + extra):
            self.file.write(B"\t")
        self.file.write(text)

    def WriteInt(self, i):
        self.file.write(bytes(str(i), "UTF-8"))

    def WriteFloat(self, f):
        if ((math.isinf(f)) or (math.isnan(f))):
            self.file.write(B"0.0")
        else:
            as_int = struct.unpack('<I', struct.pack('<f', f))[0]
            as_hex = hex(as_int)                  # As hex string "0x2f"
            #as_pad = "{0:#010x}".format(as_int)  # As hex string padded with 0s "0x2f000000"
            #as_str = str(f)                      # As string "3.5"
            self.file.write(bytes(as_hex, "UTF-8"))

    def WriteMatrix(self, matrix):
        self.IndentWrite(B"{", 1)
        self.WriteFloat(matrix[0][0])
        self.Write(B", ")
        self.WriteFloat(matrix[1][0])
        self.Write(B", ")
        self.WriteFloat(matrix[2][0])
        self.Write(B", ")
        self.WriteFloat(matrix[3][0])
        self.Write(B",\n")

        self.IndentWrite(B" ", 1)
        self.WriteFloat(matrix[0][1])
        self.Write(B", ")
        self.WriteFloat(matrix[1][1])
        self.Write(B", ")
        self.WriteFloat(matrix[2][1])
        self.Write(B", ")
        self.WriteFloat(matrix[3][1])
        self.Write(B",\n")

        self.IndentWrite(B" ", 1)
        self.WriteFloat(matrix[0][2])
        self.Write(B", ")
        self.WriteFloat(matrix[1][2])
        self.Write(B", ")
        self.WriteFloat(matrix[2][2])
        self.Write(B", ")
        self.WriteFloat(matrix[3][2])
        self.Write(B",\n")

        self.IndentWrite(B" ", 1)
        self.WriteFloat(matrix[0][3])
        self.Write(B", ")
        self.WriteFloat(matrix[1][3])
        self.Write(B", ")
        self.WriteFloat(matrix[2][3])
        self.Write(B", ")
        self.WriteFloat(matrix[3][3])
        self.Write(B"}\n")

    def WriteMatrixFlat(self, matrix):
        self.IndentWrite(B"{", 1)
        self.WriteFloat(matrix[0][0])
        self.Write(B", ")
        self.WriteFloat(matrix[1][0])
        self.Write(B", ")
        self.WriteFloat(matrix[2][0])
        self.Write(B", ")
        self.WriteFloat(matrix[3][0])
        self.Write(B", ")
        self.WriteFloat(matrix[0][1])
        self.Write(B", ")
        self.WriteFloat(matrix[1][1])
        self.Write(B", ")
        self.WriteFloat(matrix[2][1])
        self.Write(B", ")
        self.WriteFloat(matrix[3][1])
        self.Write(B", ")
        self.WriteFloat(matrix[0][2])
        self.Write(B", ")
        self.WriteFloat(matrix[1][2])
        self.Write(B", ")
        self.WriteFloat(matrix[2][2])
        self.Write(B", ")
        self.WriteFloat(matrix[3][2])
        self.Write(B", ")
        self.WriteFloat(matrix[0][3])
        self.Write(B", ")
        self.WriteFloat(matrix[1][3])
        self.Write(B", ")
        self.WriteFloat(matrix[2][3])
        self.Write(B", ")
        self.WriteFloat(matrix[3][3])
        self.Write(B"}")

    def WriteColor(self, color):
        self.Write(B"{")
        self.WriteFloat(color[0])
        self.Write(B", ")
        self.WriteFloat(color[1])
        self.Write(B", ")
        self.WriteFloat(color[2])
        self.Write(B"}")

    def WriteFileName(self, filename):
        length = len(filename)
        if (length != 0):
            if ((length > 2) and (filename[1] == ":")):
                self.Write(B"//")
                self.Write(bytes(filename[0], "UTF-8"))
                self.Write(bytes(filename[2:length].replace("\\", "/"), "UTF-8"))
            else:
                self.Write(bytes(filename.replace("\\", "/"), "UTF-8"))

    def WriteIntArray(self, valueArray):
        count = len(valueArray)
        k = 0

        lineCount = count >> 6
        for i in range(lineCount):
            self.IndentWrite(B"", 1)
            for j in range(63):
                self.WriteInt(valueArray[k])
                self.Write(B", ")
                k += 1

            self.WriteInt(valueArray[k])
            k += 1

            if (i * 64 < count - 64):
                self.Write(B",\n")
            else:
                self.Write(B"\n")

        count &= 63
        if (count != 0):
            self.IndentWrite(B"", 1)
            for j in range(count - 1):
                self.WriteInt(valueArray[k])
                self.Write(B", ")
                k += 1

            self.WriteInt(valueArray[k])
            self.Write(B"\n")

    def WriteFloatArray(self, valueArray):
        count = len(valueArray)
        k = 0

        lineCount = count >> 4
        for i in range(lineCount):
            self.IndentWrite(B"", 1)
            for j in range(15):
                self.WriteFloat(valueArray[k])
                self.Write(B", ")
                k += 1

            self.WriteFloat(valueArray[k])
            k += 1

            if (i * 16 < count - 16):
                self.Write(B",\n")
            else:
                self.Write(B"\n")

        count &= 15
        if (count != 0):
            self.IndentWrite(B"", 1)
            for j in range(count - 1):
                self.WriteFloat(valueArray[k])
                self.Write(B", ")
                k += 1

            self.WriteFloat(valueArray[k])
            self.Write(B"\n")

    def WriteVector2D(self, vector):
        self.Write(B"{")
        self.WriteFloat(vector[0])
        self.Write(B", ")
        self.WriteFloat(vector[1])
        self.Write(B"}")

    def WriteVector3D(self, vector):
        self.Write(B"{")
        self.WriteFloat(vector[0])
        self.Write(B", ")
        self.WriteFloat(vector[1])
        self.Write(B", ")
        self.WriteFloat(vector[2])
        self.Write(B"}")

    def WriteVector4D(self, vector):
        self.Write(B"{")
        self.WriteFloat(vector[0])
        self.Write(B", ")
        self.WriteFloat(vector[1])
        self.Write(B", ")
        self.WriteFloat(vector[2])
        self.Write(B", ")
        self.WriteFloat(vector[3])
        self.Write(B"}")

    def WriteQuaternion(self, quaternion):
        self.Write(B"{")
        self.WriteFloat(quaternion[1])
        self.Write(B", ")
        self.WriteFloat(quaternion[2])
        self.Write(B", ")
        self.WriteFloat(quaternion[3])
        self.Write(B", ")
        self.WriteFloat(quaternion[0])
        self.Write(B"}")

    def WriteVertexArray2D(self, vertexArray, attrib):
        count = len(vertexArray)
        k = 0

        lineCount = count >> 3
        for i in range(lineCount):
            self.IndentWrite(B"", 1)
            for j in range(7):
                self.WriteVector2D(getattr(vertexArray[k], attrib))
                self.Write(B", ")
                k += 1

            self.WriteVector2D(getattr(vertexArray[k], attrib))
            k += 1

            if (i * 8 < count - 8):
                self.Write(B",\n")
            else:
                self.Write(B"\n")

        count &= 7
        if (count != 0):
            self.IndentWrite(B"", 1)
            for j in range(count - 1):
                self.WriteVector2D(getattr(vertexArray[k], attrib))
                self.Write(B", ")
                k += 1

            self.WriteVector2D(getattr(vertexArray[k], attrib))
            self.Write(B"\n")

    def WriteVertexArray3D(self, vertexArray, attrib):
        count = len(vertexArray)
        k = 0

        lineCount = count >> 3
        for i in range(lineCount):
            self.IndentWrite(B"", 1)
            for j in range(7):
                self.WriteVector3D(getattr(vertexArray[k], attrib))
                self.Write(B", ")
                k += 1

            self.WriteVector3D(getattr(vertexArray[k], attrib))
            k += 1

            if (i * 8 < count - 8):
                self.Write(B",\n")
            else:
                self.Write(B"\n")

        count &= 7
        if (count != 0):
            self.IndentWrite(B"", 1)
            for j in range(count - 1):
                self.WriteVector3D(getattr(vertexArray[k], attrib))
                self.Write(B", ")
                k += 1

            self.WriteVector3D(getattr(vertexArray[k], attrib))
            self.Write(B"\n")

    def WriteMorphPositionArray3D(self, vertexArray, meshVertexArray):
        count = len(vertexArray)
        k = 0

        lineCount = count >> 3
        for i in range(lineCount):
            self.IndentWrite(B"", 1)
            for j in range(7):
                self.WriteVector3D(meshVertexArray[vertexArray[k].vertexIndex].co)
                self.Write(B", ")
                k += 1

            self.WriteVector3D(meshVertexArray[vertexArray[k].vertexIndex].co)
            k += 1

            if (i * 8 < count - 8):
                self.Write(B",\n")
            else:
                self.Write(B"\n")

        count &= 7
        if (count != 0):
            self.IndentWrite(B"", 1)
            for j in range(count - 1):
                self.WriteVector3D(meshVertexArray[vertexArray[k].vertexIndex].co)
                self.Write(B", ")
                k += 1

            self.WriteVector3D(meshVertexArray[vertexArray[k].vertexIndex].co)
            self.Write(B"\n")

    def WriteMorphNormalArray3D(self, vertexArray, meshVertexArray, tessFaceArray):
        count = len(vertexArray)
        k = 0

        lineCount = count >> 3
        for i in range(lineCount):
            self.IndentWrite(B"", 1)
            for j in range(7):
                face = tessFaceArray[vertexArray[k].faceIndex]
                self.WriteVector3D(meshVertexArray[vertexArray[k].vertexIndex].normal if (face.use_smooth) else face.normal)
                self.Write(B", ")
                k += 1

            face = tessFaceArray[vertexArray[k].faceIndex]
            self.WriteVector3D(meshVertexArray[vertexArray[k].vertexIndex].normal if (face.use_smooth) else face.normal)
            k += 1

            if (i * 8 < count - 8):
                self.Write(B",\n")
            else:
                self.Write(B"\n")

        count &= 7
        if (count != 0):
            self.IndentWrite(B"", 1)
            for j in range(count - 1):
                face = tessFaceArray[vertexArray[k].faceIndex]
                self.WriteVector3D(meshVertexArray[vertexArray[k].vertexIndex].normal if (face.use_smooth) else face.normal)
                self.Write(B", ")
                k += 1

            face = tessFaceArray[vertexArray[k].faceIndex]
            self.WriteVector3D(meshVertexArray[vertexArray[k].vertexIndex].normal if (face.use_smooth) else face.normal)
            self.Write(B"\n")

    def WriteTriangle(self, triangleIndex, indexTable):
        i = triangleIndex * 3
        self.Write(B"{")
        self.WriteInt(indexTable[i])
        self.Write(B", ")
        self.WriteInt(indexTable[i + 1])
        self.Write(B", ")
        self.WriteInt(indexTable[i + 2])
        self.Write(B"}")

    def WriteTriangleArray(self, count, indexTable):
        triangleIndex = 0

        lineCount = count >> 4
        for i in range(lineCount):
            self.IndentWrite(B"", 1)
            for j in range(15):
                self.WriteTriangle(triangleIndex, indexTable)
                self.Write(B", ")
                triangleIndex += 1

            self.WriteTriangle(triangleIndex, indexTable)
            triangleIndex += 1

            if (i * 16 < count - 16):
                self.Write(B",\n")
            else:
                self.Write(B"\n")

        count &= 15
        if (count != 0):
            self.IndentWrite(B"", 1)
            for j in range(count - 1):
                self.WriteTriangle(triangleIndex, indexTable)
                self.Write(B", ")
                triangleIndex += 1

            self.WriteTriangle(triangleIndex, indexTable)
            self.Write(B"\n")

    def WriteNodeTable(self, objectRef):
        first = True
        for node in objectRef[1]["nodeTable"]:
            if (first):
                self.Write(B"\t\t// ")
            else:
                self.Write(B", ")
            self.Write(bytes(node.name, "UTF-8"))
            first = False

    @staticmethod
    def GetNodeType(node):
        if (node.type == "MESH"):
            if (len(node.data.polygons) != 0):
                return (kNodeTypeGeometry)
        elif (node.type == "LIGHT"):
            type = node.data.type
            if ((type == "SUN") or (type == "POINT") or (type == "SPOT")):
                return (kNodeTypeLight)
        elif (node.type == "CAMERA"):
            return (kNodeTypeCamera)

        return (kNodeTypeNode)

    @staticmethod
    def GetShapeKeys(mesh):
        shapeKeys = mesh.shape_keys
        if ((shapeKeys) and (len(shapeKeys.key_blocks) > 1)):
            return (shapeKeys)

        return (None)

    def FindNode(self, name):
        for nodeRef in self.nodeArray.items():
            if (nodeRef[0].name == name):
                return (nodeRef)
        return (None)

    @staticmethod
    def DeindexMesh(mesh, materialTable):

        # This function deindexes all vertex positions, colors, and texcoords.
        # Three separate ExportVertex structures are created for each triangle.

        vertexArray = mesh.vertices
        exportVertexArray = []
        faceIndex = 0

        for face in mesh.loop_triangles:
            assert(len(face.vertices) == 3)

            k1 = face.vertices[0]
            k2 = face.vertices[1]
            k3 = face.vertices[2]

            v1 = vertexArray[k1]
            v2 = vertexArray[k2]
            v3 = vertexArray[k3]

            exportVertex = ExportVertex()
            exportVertex.vertexIndex = k1
            exportVertex.faceIndex = faceIndex
            exportVertex.position = v1.co
            exportVertex.normal = v1.normal if (face.use_smooth) else face.normal
            exportVertexArray.append(exportVertex)

            exportVertex = ExportVertex()
            exportVertex.vertexIndex = k2
            exportVertex.faceIndex = faceIndex
            exportVertex.position = v2.co
            exportVertex.normal = v2.normal if (face.use_smooth) else face.normal
            exportVertexArray.append(exportVertex)

            exportVertex = ExportVertex()
            exportVertex.vertexIndex = k3
            exportVertex.faceIndex = faceIndex
            exportVertex.position = v3.co
            exportVertex.normal = v3.normal if (face.use_smooth) else face.normal
            exportVertexArray.append(exportVertex)

            materialTable.append(face.material_index)
            faceIndex += 1

        colorCount = len(mesh.vertex_colors)
        if (colorCount > 0):
            colorFace = mesh.vertex_colors[0].data
            vertexIndex = 0
            faceIndex = 0

            for face in mesh.loop_triangles:
                cf = colorFace[faceIndex]
                exportVertexArray[vertexIndex].color = cf.color1
                vertexIndex += 1
                exportVertexArray[vertexIndex].color = cf.color2
                vertexIndex += 1
                exportVertexArray[vertexIndex].color = cf.color3
                vertexIndex += 1
                faceIndex += 1

        # TODO: Export multiple UV layers
        # https://wiki.blender.org/wiki/Reference/Release_Notes/2.80/Python_API/Mesh_API
        #for uv_layer in mesh.uv_layers:
            #    for tri in mesh.loop_triangles:
            #        for loop_index in tri.loops:
            #            exportVertexArray[vertexIndex].texcoord0 = uv_layer.data[loop_index].uv
            #            vertexIndex += 1

        texcoordCount = len(mesh.uv_layers)
        if (texcoordCount > 0):
            vertexIndex = 0
            for uv_layer in mesh.uv_layers:
                for tri in mesh.loop_triangles:
                    exportVertexArray[vertexIndex].texcoord0 = mesh.uv_layers[0].data[0].uv
                    vertexIndex += 1
                    exportVertexArray[vertexIndex].texcoord0 = mesh.uv_layers[0].data[1].uv
                    vertexIndex += 1
                    exportVertexArray[vertexIndex].texcoord0 = mesh.uv_layers[0].data[2].uv
                    vertexIndex += 1

            if (texcoordCount > 1):
                vertexIndex = 0
                for uv_layer in mesh.uv_layers:
                    for tri in mesh.loop_triangles:
                        exportVertexArray[vertexIndex].texcoord0 = mesh.uv_layers[1].data[0].uv
                        vertexIndex += 1
                        exportVertexArray[vertexIndex].texcoord0 = mesh.uv_layers[1].data[1].uv
                        vertexIndex += 1
                        exportVertexArray[vertexIndex].texcoord0 = mesh.uv_layers[1].data[2].uv
                        vertexIndex += 1

        for ev in exportVertexArray:
            ev.Hash()

        return (exportVertexArray)

    @staticmethod
    def FindExportVertex(bucket, exportVertexArray, vertex):
        for index in bucket:
            if (exportVertexArray[index] == vertex):
                return (index)

        return (-1)

    # TODO: Remove duplicates in Blender? Does applying modifiers somehow create dupes sometimes? Seems unlikely enough for
    # this performance cost not to be worth it.
    @staticmethod
    def UnifyVertices(exportVertexArray, indexTable):

        # This function looks for identical vertices having exactly the same position, normal,
        # color, and texcoords. Duplicate vertices are unified, and a new index table is returned.

        bucketCount = len(exportVertexArray) >> 3
        if (bucketCount > 1):

            # Round down to nearest power of two.

            while True:
                count = bucketCount & (bucketCount - 1)
                if (count == 0):
                    break
                bucketCount = count
        else:
            bucketCount = 1

        hashTable = [[] for i in range(bucketCount)]
        unifiedVertexArray = []

        for i in range(len(exportVertexArray)):
            ev = exportVertexArray[i]
            bucket = ev.hash & (bucketCount - 1)
            index = OpenGexExporter.FindExportVertex(hashTable[bucket], exportVertexArray, ev)
            if (index < 0):
                indexTable.append(len(unifiedVertexArray))
                unifiedVertexArray.append(ev)
                hashTable[bucket].append(i)
            else:
                indexTable.append(indexTable[index])

        return (unifiedVertexArray)

    def ProcessBone(self, bone):
        if ((self.exportAllFlag) or (bone.select)):
            self.nodeArray[bone] = {"nodeType" : kNodeTypeBone, "structName" : bytes("node" + str(len(self.nodeArray) + 1), "UTF-8")}

        for subnode in bone.children:
            self.ProcessBone(subnode)

    def ProcessNode(self, node):
        if ((self.exportAllFlag) or (node.select)):
            type = OpenGexExporter.GetNodeType(node)
            self.nodeArray[node] = {"nodeType" : type, "structName" : bytes("node" + str(len(self.nodeArray) + 1), "UTF-8")}

            if (node.parent_type == "BONE"):
                boneSubnodeArray = self.boneParentArray.get(node.parent_bone)
                if (boneSubnodeArray):
                    boneSubnodeArray.append(node)
                else:
                    self.boneParentArray[node.parent_bone] = [node]

            if (node.type == "ARMATURE"):
                skeleton = node.data
                if (skeleton):
                    for bone in skeleton.bones:
                        if (not bone.parent):
                            self.ProcessBone(bone)

        for subnode in node.children:
            self.ProcessNode(subnode)

    def ProcessSkinnedMeshes(self):
        for nodeRef in self.nodeArray.items():
            if (nodeRef[1]["nodeType"] == kNodeTypeGeometry):
                armature = nodeRef[0].find_armature()
                if (armature):
                    for bone in armature.data.bones:
                        boneRef = self.FindNode(bone.name)
                        if (boneRef):
                            # If a node is used as a bone, then we force its type to be a bone.
                            boneRef[1]["nodeType"] = kNodeTypeBone

    @staticmethod
    def ClassifyAnimationCurve(fcurve):
        linearCount = 0
        bezierCount = 0

        for key in fcurve.keyframe_points:
            interp = key.interpolation
            if (interp == "LINEAR"):
                linearCount += 1
            elif (interp == "BEZIER"):
                bezierCount += 1
            else:
                return (kAnimationSampled)

        if (bezierCount == 0):
            return (kAnimationLinear)
        elif (linearCount == 0):
            return (kAnimationBezier)

        return (kAnimationSampled)

    @staticmethod
    def AnimationKeysDifferent(fcurve):
        keyCount = len(fcurve.keyframe_points)
        if (keyCount > 0):
            key1 = fcurve.keyframe_points[0].co[1]

            for i in range(1, keyCount):
                key2 = fcurve.keyframe_points[i].co[1]
                if (math.fabs(key2 - key1) > kExportEpsilon):
                    return (True)

        return (False)

    @staticmethod
    def AnimationTangentsNonzero(fcurve):
        keyCount = len(fcurve.keyframe_points)
        if (keyCount > 0):
            key = fcurve.keyframe_points[0].co[1]
            left = fcurve.keyframe_points[0].handle_left[1]
            right = fcurve.keyframe_points[0].handle_right[1]
            if ((math.fabs(key - left) > kExportEpsilon) or (math.fabs(right - key) > kExportEpsilon)):
                return (True)

            for i in range(1, keyCount):
                key = fcurve.keyframe_points[i].co[1]
                left = fcurve.keyframe_points[i].handle_left[1]
                right = fcurve.keyframe_points[i].handle_right[1]
                if ((math.fabs(key - left) > kExportEpsilon) or (math.fabs(right - key) > kExportEpsilon)):
                    return (True)

        return (False)

    @staticmethod
    def AnimationPresent(fcurve, kind):
        if (kind != kAnimationBezier):
            return (OpenGexExporter.AnimationKeysDifferent(fcurve))

        return ((OpenGexExporter.AnimationKeysDifferent(fcurve)) or (OpenGexExporter.AnimationTangentsNonzero(fcurve)))

    @staticmethod
    def MatricesDifferent(m1, m2):
        for i in range(4):
            for j in range(4):
                if (math.fabs(m1[i][j] - m2[i][j]) > kExportEpsilon):
                    return (True)

        return (False)

    @staticmethod
    def CollectBoneAnimation(armature, name):
        path = "pose.bones[\"" + name + "\"]."
        curveArray = []

        if (armature.animation_data):
            action = armature.animation_data.action
            if (action):
                for fcurve in action.fcurves:
                    if (fcurve.data_path.startswith(path)):
                        curveArray.append(fcurve)

        return (curveArray)

    def ExportKeyTimes(self, fcurve):
        self.IndentWrite(B"Key {float {")

        keyCount = len(fcurve.keyframe_points)
        for i in range(keyCount):
            if (i > 0):
                self.Write(B", ")

            time = fcurve.keyframe_points[i].co[0] - self.beginFrame
            self.WriteFloat(time * self.frameTime)

        self.Write(B"}}\n")

    def ExportKeyTimeControlPoints(self, fcurve):
        self.IndentWrite(B"Key (kind = \"-control\") {float {")

        keyCount = len(fcurve.keyframe_points)
        for i in range(keyCount):
            if (i > 0):
                self.Write(B", ")

            ctrl = fcurve.keyframe_points[i].handle_left[0] - self.beginFrame
            self.WriteFloat(ctrl * self.frameTime)

        self.Write(B"}}\n")
        self.IndentWrite(B"Key (kind = \"+control\") {float {")

        for i in range(keyCount):
            if (i > 0):
                self.Write(B", ")

            ctrl = fcurve.keyframe_points[i].handle_right[0] - self.beginFrame
            self.WriteFloat(ctrl * self.frameTime)

        self.Write(B"}}\n")

    def ExportKeyValues(self, fcurve):
        self.IndentWrite(B"Key {float {")

        keyCount = len(fcurve.keyframe_points)
        for i in range(keyCount):
            if (i > 0):
                self.Write(B", ")

            value = fcurve.keyframe_points[i].co[1]
            self.WriteFloat(value)

        self.Write(B"}}\n")

    def ExportKeyValueControlPoints(self, fcurve):
        self.IndentWrite(B"Key (kind = \"-control\") {float {")

        keyCount = len(fcurve.keyframe_points)
        for i in range(keyCount):
            if (i > 0):
                self.Write(B", ")

            ctrl = fcurve.keyframe_points[i].handle_left[1]
            self.WriteFloat(ctrl)

        self.Write(B"}}\n")
        self.IndentWrite(B"Key (kind = \"+control\") {float {")

        for i in range(keyCount):
            if (i > 0):
                self.Write(B", ")

            ctrl = fcurve.keyframe_points[i].handle_right[1]
            self.WriteFloat(ctrl)

        self.Write(B"}}\n")

    def ExportAnimationTrack(self, fcurve, kind, target, newline):

        # This function exports a single animation track. The curve types for the
        # Time and Value structures are given by the kind parameter.

        self.IndentWrite(B"Track (target = %", 0, newline)
        self.Write(target)
        self.Write(B")\n")
        self.IndentWrite(B"{\n")
        self.indentLevel += 1

        if (kind != kAnimationBezier):
            self.IndentWrite(B"Time\n")
            self.IndentWrite(B"{\n")
            self.indentLevel += 1

            self.ExportKeyTimes(fcurve)

            self.IndentWrite(B"}\n\n", -1)
            self.IndentWrite(B"Value\n", -1)
            self.IndentWrite(B"{\n", -1)

            self.ExportKeyValues(fcurve)

            self.indentLevel -= 1
            self.IndentWrite(B"}\n")
        else:
            self.IndentWrite(B"Time (curve = \"bezier\")\n")
            self.IndentWrite(B"{\n")
            self.indentLevel += 1

            self.ExportKeyTimes(fcurve)
            self.ExportKeyTimeControlPoints(fcurve)

            self.IndentWrite(B"}\n\n", -1)
            self.IndentWrite(B"Value (curve = \"bezier\")\n", -1)
            self.IndentWrite(B"{\n", -1)

            self.ExportKeyValues(fcurve)
            self.ExportKeyValueControlPoints(fcurve)

            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

    def ExportNodeSampledAnimation(self, node, scene):

        # This function exports animation as full 4x4 matrices for each frame.

        currentFrame = scene.frame_current
        currentSubframe = scene.frame_subframe

        animationFlag = False
        m1 = node.matrix_local.copy()

        for i in range(self.beginFrame, self.endFrame):
            scene.frame_set(i)
            m2 = node.matrix_local
            if (OpenGexExporter.MatricesDifferent(m1, m2)):
                animationFlag = True
                break

        if (animationFlag):
            self.IndentWrite(B"Animation\n", 0, True)
            self.IndentWrite(B"{\n")
            self.indentLevel += 1

            self.IndentWrite(B"Track (target = %transform)\n")
            self.IndentWrite(B"{\n")
            self.indentLevel += 1

            self.IndentWrite(B"Time\n")
            self.IndentWrite(B"{\n")
            self.indentLevel += 1

            self.IndentWrite(B"Key {float {")

            for i in range(self.beginFrame, self.endFrame):
                self.WriteFloat((i - self.beginFrame) * self.frameTime)
                self.Write(B", ")

            self.WriteFloat(self.endFrame * self.frameTime)
            self.Write(B"}}\n")

            self.IndentWrite(B"}\n\n", -1)
            self.IndentWrite(B"Value\n", -1)
            self.IndentWrite(B"{\n", -1)

            self.IndentWrite(B"Key\n")
            self.IndentWrite(B"{\n")
            self.indentLevel += 1

            self.IndentWrite(B"float[16]\n")
            self.IndentWrite(B"{\n")

            for i in range(self.beginFrame, self.endFrame):
                scene.frame_set(i)
                self.WriteMatrixFlat(node.matrix_local)
                self.Write(B",\n")

            scene.frame_set(self.endFrame)
            self.WriteMatrixFlat(node.matrix_local)
            self.IndentWrite(B"}\n", 0, True)

            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

        scene.frame_set(currentFrame, subframe=currentSubframe)

    def ExportBoneSampledAnimation(self, poseBone, scene):

        # This function exports bone animation as full 4x4 matrices for each frame.

        currentFrame = scene.frame_current
        currentSubframe = scene.frame_subframe

        animationFlag = False
        m1 = poseBone.matrix.copy()

        for i in range(self.beginFrame, self.endFrame):
            scene.frame_set(i)
            m2 = poseBone.matrix
            if (OpenGexExporter.MatricesDifferent(m1, m2)):
                animationFlag = True
                break

        if (animationFlag):
            self.IndentWrite(B"Animation\n", 0, True)
            self.IndentWrite(B"{\n")
            self.indentLevel += 1

            self.IndentWrite(B"Track (target = %transform)\n")
            self.IndentWrite(B"{\n")
            self.indentLevel += 1

            self.IndentWrite(B"Time\n")
            self.IndentWrite(B"{\n")
            self.indentLevel += 1

            self.IndentWrite(B"Key {float {")

            for i in range(self.beginFrame, self.endFrame):
                self.WriteFloat((i - self.beginFrame) * self.frameTime)
                self.Write(B", ")

            self.WriteFloat(self.endFrame * self.frameTime)
            self.Write(B"}}\n")

            self.IndentWrite(B"}\n\n", -1)
            self.IndentWrite(B"Value\n", -1)
            self.IndentWrite(B"{\n", -1)

            self.IndentWrite(B"Key\n")
            self.IndentWrite(B"{\n")
            self.indentLevel += 1

            self.IndentWrite(B"float[16]\n")
            self.IndentWrite(B"{\n")

            parent = poseBone.parent
            if (parent):
                for i in range(self.beginFrame, self.endFrame):
                    scene.frame_set(i)
                    if (math.fabs(parent.matrix.determinant()) > kExportEpsilon):
                        self.WriteMatrixFlat(parent.matrix.inverted() @ poseBone.matrix)
                    else:
                        self.WriteMatrixFlat(poseBone.matrix)

                    self.Write(B",\n")

                scene.frame_set(self.endFrame)
                if (math.fabs(parent.matrix.determinant()) > kExportEpsilon):
                    self.WriteMatrixFlat(parent.matrix.inverted() @ poseBone.matrix)
                else:
                    self.WriteMatrixFlat(poseBone.matrix)

                self.IndentWrite(B"}\n", 0, True)

            else:
                for i in range(self.beginFrame, self.endFrame):
                    scene.frame_set(i)
                    self.WriteMatrixFlat(poseBone.matrix)
                    self.Write(B",\n")

                scene.frame_set(self.endFrame)
                self.WriteMatrixFlat(poseBone.matrix)
                self.IndentWrite(B"}\n", 0, True)

            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

        scene.frame_set(currentFrame, subframe=currentSubframe)

    def ExportMorphWeightSampledAnimationTrack(self, block, target, scene, newline):
        currentFrame = scene.frame_current
        currentSubframe = scene.frame_subframe

        self.IndentWrite(B"Track (target = %", 0, newline)
        self.Write(target)
        self.Write(B")\n")
        self.IndentWrite(B"{\n")
        self.indentLevel += 1

        self.IndentWrite(B"Time\n")
        self.IndentWrite(B"{\n")
        self.indentLevel += 1

        self.IndentWrite(B"Key {float {")

        for i in range(self.beginFrame, self.endFrame):
            self.WriteFloat((i - self.beginFrame) * self.frameTime)
            self.Write(B", ")

        self.WriteFloat(self.endFrame * self.frameTime)
        self.Write(B"}}\n")

        self.IndentWrite(B"}\n\n", -1)
        self.IndentWrite(B"Value\n", -1)
        self.IndentWrite(B"{\n", -1)

        self.IndentWrite(B"Key {float {")

        for i in range(self.beginFrame, self.endFrame):
            scene.frame_set(i)
            self.WriteFloat(block.value)
            self.Write(B", ")

        scene.frame_set(self.endFrame)
        self.WriteFloat(block.value)
        self.Write(B"}}\n")

        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

        scene.frame_set(currentFrame, subframe=currentSubframe)

    def ExportNodeTransform(self, node, scene):
        posAnimCurve = [None, None, None]
        rotAnimCurve = [None, None, None]
        sclAnimCurve = [None, None, None]
        posAnimKind = [0, 0, 0]
        rotAnimKind = [0, 0, 0]
        sclAnimKind = [0, 0, 0]

        deltaPosAnimCurve = [None, None, None]
        deltaRotAnimCurve = [None, None, None]
        deltaSclAnimCurve = [None, None, None]
        deltaPosAnimKind = [0, 0, 0]
        deltaRotAnimKind = [0, 0, 0]
        deltaSclAnimKind = [0, 0, 0]

        positionAnimated = False
        rotationAnimated = False
        scaleAnimated = False
        posAnimated = [False, False, False]
        rotAnimated = [False, False, False]
        sclAnimated = [False, False, False]

        deltaPositionAnimated = False
        deltaRotationAnimated = False
        deltaScaleAnimated = False
        deltaPosAnimated = [False, False, False]
        deltaRotAnimated = [False, False, False]
        deltaSclAnimated = [False, False, False]

        mode = node.rotation_mode
        sampledAnimation = ((self.sampleAnimationFlag) or (mode == "QUATERNION") or (mode == "AXIS_ANGLE"))

        if ((not sampledAnimation) and (node.animation_data)):
            action = node.animation_data.action
            if (action):
                for fcurve in action.fcurves:
                    kind = OpenGexExporter.ClassifyAnimationCurve(fcurve)
                    if (kind != kAnimationSampled):
                        if (fcurve.data_path == "location"):
                            for i in range(3):
                                if ((fcurve.array_index == i) and (not posAnimCurve[i])):
                                    posAnimCurve[i] = fcurve
                                    posAnimKind[i] = kind
                                    if (OpenGexExporter.AnimationPresent(fcurve, kind)):
                                        posAnimated[i] = True
                        elif (fcurve.data_path == "delta_location"):
                            for i in range(3):
                                if ((fcurve.array_index == i) and (not deltaPosAnimCurve[i])):
                                    deltaPosAnimCurve[i] = fcurve
                                    deltaPosAnimKind[i] = kind
                                    if (OpenGexExporter.AnimationPresent(fcurve, kind)):
                                        deltaPosAnimated[i] = True
                        elif (fcurve.data_path == "rotation_euler"):
                            for i in range(3):
                                if ((fcurve.array_index == i) and (not rotAnimCurve[i])):
                                    rotAnimCurve[i] = fcurve
                                    rotAnimKind[i] = kind
                                    if (OpenGexExporter.AnimationPresent(fcurve, kind)):
                                        rotAnimated[i] = True
                        elif (fcurve.data_path == "delta_rotation_euler"):
                            for i in range(3):
                                if ((fcurve.array_index == i) and (not deltaRotAnimCurve[i])):
                                    deltaRotAnimCurve[i] = fcurve
                                    deltaRotAnimKind[i] = kind
                                    if (OpenGexExporter.AnimationPresent(fcurve, kind)):
                                        deltaRotAnimated[i] = True
                        elif (fcurve.data_path == "scale"):
                            for i in range(3):
                                if ((fcurve.array_index == i) and (not sclAnimCurve[i])):
                                    sclAnimCurve[i] = fcurve
                                    sclAnimKind[i] = kind
                                    if (OpenGexExporter.AnimationPresent(fcurve, kind)):
                                        sclAnimated[i] = True
                        elif (fcurve.data_path == "delta_scale"):
                            for i in range(3):
                                if ((fcurve.array_index == i) and (not deltaSclAnimCurve[i])):
                                    deltaSclAnimCurve[i] = fcurve
                                    deltaSclAnimKind[i] = kind
                                    if (OpenGexExporter.AnimationPresent(fcurve, kind)):
                                        deltaSclAnimated[i] = True
                        elif ((fcurve.data_path == "rotation_axis_angle") or (fcurve.data_path == "rotation_quaternion") or (fcurve.data_path == "delta_rotation_quaternion")):
                            sampledAnimation = True
                            break
                    else:
                        sampledAnimation = True
                        break

        positionAnimated = posAnimated[0] | posAnimated[1] | posAnimated[2]
        rotationAnimated = rotAnimated[0] | rotAnimated[1] | rotAnimated[2]
        scaleAnimated = sclAnimated[0] | sclAnimated[1] | sclAnimated[2]

        deltaPositionAnimated = deltaPosAnimated[0] | deltaPosAnimated[1] | deltaPosAnimated[2]
        deltaRotationAnimated = deltaRotAnimated[0] | deltaRotAnimated[1] | deltaRotAnimated[2]
        deltaScaleAnimated = deltaSclAnimated[0] | deltaSclAnimated[1] | deltaSclAnimated[2]

        if ((sampledAnimation) or ((not positionAnimated) and (not rotationAnimated) and (not scaleAnimated) and (not deltaPositionAnimated) and (not deltaRotationAnimated) and (not deltaScaleAnimated))):

            # If there's no keyframe animation at all, then write the node transform as a single 4x4 matrix.
            # We might still be exporting sampled animation below.

            self.IndentWrite(B"Transform")

            if (sampledAnimation):
                self.Write(B" %transform")

            self.IndentWrite(B"{\n", 0, True)
            self.indentLevel += 1

            self.IndentWrite(B"float[16]\n")
            self.IndentWrite(B"{\n")
            self.WriteMatrix(node.matrix_local)
            self.IndentWrite(B"}\n")

            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

            if (sampledAnimation):
                self.ExportNodeSampledAnimation(node, scene)

        else:
            structFlag = False

            deltaTranslation = node.delta_location
            if (deltaPositionAnimated):

                # When the delta location is animated, write the x, y, and z components separately
                # so they can be targeted by different tracks having different sets of keys.

                for i in range(3):
                    pos = deltaTranslation[i]
                    if ((deltaPosAnimated[i]) or (math.fabs(pos) > kExportEpsilon)):
                        self.IndentWrite(B"Translation %", 0, structFlag)
                        self.Write(deltaSubtranslationName[i])
                        self.Write(B" (kind = \"")
                        self.Write(axisName[i])
                        self.Write(B"\")\n")
                        self.IndentWrite(B"{\n")
                        self.IndentWrite(B"float {", 1)
                        self.WriteFloat(pos)
                        self.Write(B"}")
                        self.IndentWrite(B"}\n", 0, True)

                        structFlag = True

            elif ((math.fabs(deltaTranslation[0]) > kExportEpsilon) or (math.fabs(deltaTranslation[1]) > kExportEpsilon) or (math.fabs(deltaTranslation[2]) > kExportEpsilon)):
                self.IndentWrite(B"Translation\n")
                self.IndentWrite(B"{\n")
                self.IndentWrite(B"float[3] {", 1)
                self.WriteVector3D(deltaTranslation)
                self.Write(B"}")
                self.IndentWrite(B"}\n", 0, True)

                structFlag = True

            translation = node.location
            if (positionAnimated):

                # When the location is animated, write the x, y, and z components separately
                # so they can be targeted by different tracks having different sets of keys.

                for i in range(3):
                    pos = translation[i]
                    if ((posAnimated[i]) or (math.fabs(pos) > kExportEpsilon)):
                        self.IndentWrite(B"Translation %", 0, structFlag)
                        self.Write(subtranslationName[i])
                        self.Write(B" (kind = \"")
                        self.Write(axisName[i])
                        self.Write(B"\")\n")
                        self.IndentWrite(B"{\n")
                        self.IndentWrite(B"float {", 1)
                        self.WriteFloat(pos)
                        self.Write(B"}")
                        self.IndentWrite(B"}\n", 0, True)

                        structFlag = True

            elif ((math.fabs(translation[0]) > kExportEpsilon) or (math.fabs(translation[1]) > kExportEpsilon) or (math.fabs(translation[2]) > kExportEpsilon)):
                self.IndentWrite(B"Translation\n")
                self.IndentWrite(B"{\n")
                self.IndentWrite(B"float[3] {", 1)
                self.WriteVector3D(translation)
                self.Write(B"}")
                self.IndentWrite(B"}\n", 0, True)

                structFlag = True

            if (deltaRotationAnimated):
                # When the delta rotation is animated, write three separate Euler angle rotations
                # so they can be targeted by different tracks having different sets of keys.

                for i in range(3):
                    axis = ord(mode[2 - i]) - 0x58
                    angle = node.delta_rotation_euler[axis]
                    if ((deltaRotAnimated[axis]) or (math.fabs(angle) > kExportEpsilon)):
                        self.IndentWrite(B"Rotation %", 0, structFlag)
                        self.Write(deltaSubrotationName[axis])
                        self.Write(B" (kind = \"")
                        self.Write(axisName[axis])
                        self.Write(B"\")\n")
                        self.IndentWrite(B"{\n")
                        self.IndentWrite(B"float {", 1)
                        self.WriteFloat(angle)
                        self.Write(B"}")
                        self.IndentWrite(B"}\n", 0, True)

                        structFlag = True

            else:
                # When the delta rotation is not animated, write it in the representation given by
                # the node's current rotation mode. (There is no axis-angle delta rotation.)

                if (mode == "QUATERNION"):
                    quaternion = node.delta_rotation_quaternion
                    if ((math.fabs(quaternion[0] - 1.0) > kExportEpsilon) or (math.fabs(quaternion[1]) > kExportEpsilon) or (math.fabs(quaternion[2]) > kExportEpsilon) or (math.fabs(quaternion[3]) > kExportEpsilon)):
                        self.IndentWrite(B"Rotation (kind = \"quaternion\")\n", 0, structFlag)
                        self.IndentWrite(B"{\n")
                        self.IndentWrite(B"float[4] {", 1)
                        self.WriteQuaternion(quaternion)
                        self.Write(B"}")
                        self.IndentWrite(B"}\n", 0, True)

                        structFlag = True

                else:
                    for i in range(3):
                        axis = ord(mode[2 - i]) - 0x58
                        angle = node.delta_rotation_euler[axis]
                        if (math.fabs(angle) > kExportEpsilon):
                            self.IndentWrite(B"Rotation (kind = \"", 0, structFlag)
                            self.Write(axisName[axis])
                            self.Write(B"\")\n")
                            self.IndentWrite(B"{\n")
                            self.IndentWrite(B"float {", 1)
                            self.WriteFloat(angle)
                            self.Write(B"}")
                            self.IndentWrite(B"}\n", 0, True)

                            structFlag = True

            if (rotationAnimated):
                # When the rotation is animated, write three separate Euler angle rotations
                # so they can be targeted by different tracks having different sets of keys.

                for i in range(3):
                    axis = ord(mode[2 - i]) - 0x58
                    angle = node.rotation_euler[axis]
                    if ((rotAnimated[axis]) or (math.fabs(angle) > kExportEpsilon)):
                        self.IndentWrite(B"Rotation %", 0, structFlag)
                        self.Write(subrotationName[axis])
                        self.Write(B" (kind = \"")
                        self.Write(axisName[axis])
                        self.Write(B"\")\n")
                        self.IndentWrite(B"{\n")
                        self.IndentWrite(B"float {", 1)
                        self.WriteFloat(angle)
                        self.Write(B"}")
                        self.IndentWrite(B"}\n", 0, True)

                        structFlag = True

            else:
                # When the rotation is not animated, write it in the representation given by
                # the node's current rotation mode.

                if (mode == "QUATERNION"):
                    quaternion = node.rotation_quaternion
                    if ((math.fabs(quaternion[0] - 1.0) > kExportEpsilon) or (math.fabs(quaternion[1]) > kExportEpsilon) or (math.fabs(quaternion[2]) > kExportEpsilon) or (math.fabs(quaternion[3]) > kExportEpsilon)):
                        self.IndentWrite(B"Rotation (kind = \"quaternion\")\n", 0, structFlag)
                        self.IndentWrite(B"{\n")
                        self.IndentWrite(B"float[4] {", 1)
                        self.WriteQuaternion(quaternion)
                        self.Write(B"}")
                        self.IndentWrite(B"}\n", 0, True)

                        structFlag = True

                elif (mode == "AXIS_ANGLE"):
                    if (math.fabs(node.rotation_axis_angle[0]) > kExportEpsilon):
                        self.IndentWrite(B"Rotation (kind = \"axis\")\n", 0, structFlag)
                        self.IndentWrite(B"{\n")
                        self.IndentWrite(B"float[4] {", 1)
                        self.WriteVector4D(node.rotation_axis_angle)
                        self.Write(B"}")
                        self.IndentWrite(B"}\n", 0, True)

                        structFlag = True

                else:
                    for i in range(3):
                        axis = ord(mode[2 - i]) - 0x58
                        angle = node.rotation_euler[axis]
                        if (math.fabs(angle) > kExportEpsilon):
                            self.IndentWrite(B"Rotation (kind = \"", 0, structFlag)
                            self.Write(axisName[axis])
                            self.Write(B"\")\n")
                            self.IndentWrite(B"{\n")
                            self.IndentWrite(B"float {", 1)
                            self.WriteFloat(angle)
                            self.Write(B"}")
                            self.IndentWrite(B"}\n", 0, True)

                            structFlag = True

            deltaScale = node.delta_scale
            if (deltaScaleAnimated):
                # When the delta scale is animated, write the x, y, and z components separately
                # so they can be targeted by different tracks having different sets of keys.

                for i in range(3):
                    scl = deltaScale[i]
                    if ((deltaSclAnimated[i]) or (math.fabs(scl) > kExportEpsilon)):
                        self.IndentWrite(B"Scale %", 0, structFlag)
                        self.Write(deltaSubscaleName[i])
                        self.Write(B" (kind = \"")
                        self.Write(axisName[i])
                        self.Write(B"\")\n")
                        self.IndentWrite(B"{\n")
                        self.IndentWrite(B"float {", 1)
                        self.WriteFloat(scl)
                        self.Write(B"}")
                        self.IndentWrite(B"}\n", 0, True)

                        structFlag = True

            elif ((math.fabs(deltaScale[0] - 1.0) > kExportEpsilon) or (math.fabs(deltaScale[1] - 1.0) > kExportEpsilon) or (math.fabs(deltaScale[2] - 1.0) > kExportEpsilon)):
                self.IndentWrite(B"Scale\n", 0, structFlag)
                self.IndentWrite(B"{\n")
                self.IndentWrite(B"float[3] {", 1)
                self.WriteVector3D(deltaScale)
                self.Write(B"}")
                self.IndentWrite(B"}\n", 0, True)

                structFlag = True

            scale = node.scale
            if (scaleAnimated):
                # When the scale is animated, write the x, y, and z components separately
                # so they can be targeted by different tracks having different sets of keys.

                for i in range(3):
                    scl = scale[i]
                    if ((sclAnimated[i]) or (math.fabs(scl) > kExportEpsilon)):
                        self.IndentWrite(B"Scale %", 0, structFlag)
                        self.Write(subscaleName[i])
                        self.Write(B" (kind = \"")
                        self.Write(axisName[i])
                        self.Write(B"\")\n")
                        self.IndentWrite(B"{\n")
                        self.IndentWrite(B"float {", 1)
                        self.WriteFloat(scl)
                        self.Write(B"}")
                        self.IndentWrite(B"}\n", 0, True)

                        structFlag = True

            elif ((math.fabs(scale[0] - 1.0) > kExportEpsilon) or (math.fabs(scale[1] - 1.0) > kExportEpsilon) or (math.fabs(scale[2] - 1.0) > kExportEpsilon)):
                self.IndentWrite(B"Scale\n", 0, structFlag)
                self.IndentWrite(B"{\n")
                self.IndentWrite(B"float[3] {", 1)
                self.WriteVector3D(scale)
                self.Write(B"}")
                self.IndentWrite(B"}\n", 0, True)

                structFlag = True

            # Export the animation tracks.

            self.IndentWrite(B"Animation (begin = ", 0, True)
            self.WriteFloat((action.frame_range[0] - self.beginFrame) * self.frameTime)
            self.Write(B", end = ")
            self.WriteFloat((action.frame_range[1] - self.beginFrame) * self.frameTime)
            self.Write(B")\n")
            self.IndentWrite(B"{\n")
            self.indentLevel += 1

            structFlag = False

            if (positionAnimated):
                for i in range(3):
                    if (posAnimated[i]):
                        self.ExportAnimationTrack(posAnimCurve[i], posAnimKind[i], subtranslationName[i], structFlag)
                        structFlag = True

            if (rotationAnimated):
                for i in range(3):
                    if (rotAnimated[i]):
                        self.ExportAnimationTrack(rotAnimCurve[i], rotAnimKind[i], subrotationName[i], structFlag)
                        structFlag = True

            if (scaleAnimated):
                for i in range(3):
                    if (sclAnimated[i]):
                        self.ExportAnimationTrack(sclAnimCurve[i], sclAnimKind[i], subscaleName[i], structFlag)
                        structFlag = True

            if (deltaPositionAnimated):
                for i in range(3):
                    if (deltaPosAnimated[i]):
                        self.ExportAnimationTrack(deltaPosAnimCurve[i], deltaPosAnimKind[i], deltaSubtranslationName[i], structFlag)
                        structFlag = True

            if (deltaRotationAnimated):
                for i in range(3):
                    if (deltaRotAnimated[i]):
                        self.ExportAnimationTrack(deltaRotAnimCurve[i], deltaRotAnimKind[i], deltaSubrotationName[i], structFlag)
                        structFlag = True

            if (deltaScaleAnimated):
                for i in range(3):
                    if (deltaSclAnimated[i]):
                        self.ExportAnimationTrack(deltaSclAnimCurve[i], deltaSclAnimKind[i], deltaSubscaleName[i], structFlag)
                        structFlag = True

            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

    def ExportBoneTransform(self, armature, bone, scene):
        curveArray = self.CollectBoneAnimation(armature, bone.name)
        animation = ((len(curveArray) != 0) or (self.sampleAnimationFlag))

        transform = bone.matrix_local.copy()
        parentBone = bone.parent
        if ((parentBone) and (math.fabs(parentBone.matrix_local.determinant()) > kExportEpsilon)):
            transform = parentBone.matrix_local.inverted() @ transform

        poseBone = armature.pose.bones.get(bone.name)
        if (poseBone):
            transform = poseBone.matrix.copy()
            parentPoseBone = poseBone.parent
            if ((parentPoseBone) and (math.fabs(parentPoseBone.matrix.determinant()) > kExportEpsilon)):
                transform = parentPoseBone.matrix.inverted() @ transform

        self.IndentWrite(B"Transform")

        if (animation):
            self.Write(B" %transform")

        self.IndentWrite(B"{\n", 0, True)
        self.indentLevel += 1

        self.IndentWrite(B"float[16]\n")
        self.IndentWrite(B"{\n")
        self.WriteMatrix(transform)
        self.IndentWrite(B"}\n")

        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

        if ((animation) and (poseBone)):
            self.ExportBoneSampledAnimation(poseBone, scene)

    def ExportMaterialRef(self, material, index):
        if (not material in self.materialArray):
            self.materialArray[material] = {"structName" : bytes("material" + str(len(self.materialArray) + 1), "UTF-8")}

        self.IndentWrite(B"MaterialRef (index = ")
        self.WriteInt(index)
        self.Write(B") {ref {$")
        self.Write(self.materialArray[material]["structName"])
        self.Write(B"}}\n")

    def ExportMorphWeights(self, node, shapeKeys, scene):
        action = None
        curveArray = []
        indexArray = []

        if (shapeKeys.animation_data):
            action = shapeKeys.animation_data.action
            if (action):
                for fcurve in action.fcurves:
                    if ((fcurve.data_path.startswith("key_blocks[")) and (fcurve.data_path.endswith("].value"))):
                        keyName = fcurve.data_path.strip("abcdehklopstuvy[]_.")
                        if ((keyName[0] == "\"") or (keyName[0] == "'")):
                            index = shapeKeys.key_blocks.find(keyName.strip("\"'"))
                            if (index >= 0):
                                curveArray.append(fcurve)
                                indexArray.append(index)
                        else:
                            curveArray.append(fcurve)
                            indexArray.append(int(keyName))

        if ((not action) and (node.animation_data)):
            action = node.animation_data.action
            if (action):
                for fcurve in action.fcurves:
                    if ((fcurve.data_path.startswith("data.shape_keys.key_blocks[")) and (fcurve.data_path.endswith("].value"))):
                        keyName = fcurve.data_path.strip("abcdehklopstuvy[]_.")
                        if ((keyName[0] == "\"") or (keyName[0] == "'")):
                            index = shapeKeys.key_blocks.find(keyName.strip("\"'"))
                            if (index >= 0):
                                curveArray.append(fcurve)
                                indexArray.append(index)
                        else:
                            curveArray.append(fcurve)
                            indexArray.append(int(keyName))

        animated = (len(curveArray) != 0)
        referenceName = shapeKeys.reference_key.name if (shapeKeys.use_relative) else ""

        for k in range(len(shapeKeys.key_blocks)):
            self.IndentWrite(B"MorphWeight", 0, (k == 0))

            if (animated):
                self.Write(B" %mw")
                self.WriteInt(k)

            self.Write(B" (index = ")
            self.WriteInt(k)
            self.Write(B") {float {")

            block = shapeKeys.key_blocks[k]
            self.WriteFloat(block.value if (block.name != referenceName) else 1.0)

            self.Write(B"}}\n")

        if (animated):
            self.IndentWrite(B"Animation (begin = ", 0, True)
            self.WriteFloat((action.frame_range[0] - self.beginFrame) * self.frameTime)
            self.Write(B", end = ")
            self.WriteFloat((action.frame_range[1] - self.beginFrame) * self.frameTime)
            self.Write(B")\n")
            self.IndentWrite(B"{\n")
            self.indentLevel += 1

            structFlag = False

            for a in range(len(curveArray)):
                k = indexArray[a]
                target = bytes("mw" + str(k), "UTF-8")

                fcurve = curveArray[a]
                kind = OpenGexExporter.ClassifyAnimationCurve(fcurve)
                if ((kind != kAnimationSampled) and (not self.sampleAnimationFlag)):
                    self.ExportAnimationTrack(fcurve, kind, target, structFlag)
                else:
                    self.ExportMorphWeightSampledAnimationTrack(shapeKeys.key_blocks[k], target, scene, structFlag)

                structFlag = True

            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

    def ExportBone(self, armature, bone, scene):
        nodeRef = self.nodeArray.get(bone)
        if (nodeRef):
            self.IndentWrite(structIdentifier[nodeRef["nodeType"]], 0, True)
            self.Write(nodeRef["structName"])

            self.IndentWrite(B"{\n", 0, True)
            self.indentLevel += 1

            name = bone.name
            if (name != ""):
                self.IndentWrite(B"Name {string {\"")
                self.Write(bytes(name, "UTF-8"))
                self.Write(B"\"}}\n\n")

            self.ExportBoneTransform(armature, bone, scene)

        for subnode in bone.children:
            self.ExportBone(armature, subnode, scene)

        # Export any ordinary nodes that are parented to this bone.

        boneSubnodeArray = self.boneParentArray.get(bone.name)
        if (boneSubnodeArray):
            poseBone = None
            if (not bone.use_relative_parent):
                poseBone = armature.pose.bones.get(bone.name)

            for subnode in boneSubnodeArray:
                self.ExportNode(subnode, scene, poseBone)

        if (nodeRef):
            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

    def ExportNode(self, node, scene, poseBone = None):
        # This function exports a single node in the scene and includes its name,
        # object reference, material references (for geometries), and transform.
        # Subnodes are then exported recursively.

        nodeRef = self.nodeArray.get(node)
        if (nodeRef):
            type = nodeRef["nodeType"]
            self.IndentWrite(structIdentifier[type], 0, True)
            self.Write(nodeRef["structName"])

            if (type == kNodeTypeGeometry):
                if (node.hide_render):
                    self.Write(B" (visible = false)")

            self.IndentWrite(B"{\n", 0, True)
            self.indentLevel += 1

            structFlag = False

            # Export the node's name if it has one.

            name = node.name
            if (name != ""):
                self.IndentWrite(B"Name {string {\"")
                self.Write(bytes(name, "UTF-8"))
                self.Write(B"\"}}\n")
                structFlag = True

            # Export the object reference and material references.

            object = node.data

            if (type == kNodeTypeGeometry):
                if (not object in self.geometryArray):
                    self.geometryArray[object] = {"structName" : bytes("geometry" + str(len(self.geometryArray) + 1), "UTF-8"), "nodeTable" : [node]}
                else:
                    self.geometryArray[object]["nodeTable"].append(node)

                self.IndentWrite(B"ObjectRef {ref {$")
                self.Write(self.geometryArray[object]["structName"])
                self.Write(B"}}\n")

                for i in range(len(node.material_slots)):
                    self.ExportMaterialRef(node.material_slots[i].material, i)

                shapeKeys = OpenGexExporter.GetShapeKeys(object)
                if (shapeKeys):
                    self.ExportMorphWeights(node, shapeKeys, scene)

                structFlag = True

            elif (type == kNodeTypeLight):
                if (not object in self.lightArray):
                    self.lightArray[object] = {"structName" : bytes("light" + str(len(self.lightArray) + 1), "UTF-8"), "nodeTable" : [node]}
                else:
                    self.lightArray[object]["nodeTable"].append(node)

                self.IndentWrite(B"ObjectRef {ref {$")
                self.Write(self.lightArray[object]["structName"])
                self.Write(B"}}\n")
                structFlag = True

            elif (type == kNodeTypeCamera):
                if (not object in self.cameraArray):
                    self.cameraArray[object] = {"structName" : bytes("camera" + str(len(self.cameraArray) + 1), "UTF-8"), "nodeTable" : [node]}
                else:
                    self.cameraArray[object]["nodeTable"].append(node)

                self.IndentWrite(B"ObjectRef {ref {$")
                self.Write(self.cameraArray[object]["structName"])
                self.Write(B"}}\n")
                structFlag = True

            if (structFlag):
                self.Write(B"\n")

            if (poseBone):

                # If the node is parented to a bone and is not relative, then undo the bone's transform.

                if (math.fabs(poseBone.matrix.determinant()) > kExportEpsilon):
                    self.IndentWrite(B"Transform\n")
                    self.IndentWrite(B"{\n")
                    self.indentLevel += 1

                    self.IndentWrite(B"float[16]\n")
                    self.IndentWrite(B"{\n")
                    self.WriteMatrix(poseBone.matrix.inverted())
                    self.IndentWrite(B"}\n")

                    self.indentLevel -= 1
                    self.IndentWrite(B"}\n\n")

            # Export the transform. If the node is animated, then animation tracks are exported here.

            self.ExportNodeTransform(node, scene)

            if (node.type == "ARMATURE"):
                skeleton = node.data
                if (skeleton):
                    for bone in skeleton.bones:
                        if (not bone.parent):
                            self.ExportBone(node, bone, scene)

        for subnode in node.children:
            if (subnode.parent_type != "BONE"):
                self.ExportNode(subnode, scene)

        if (nodeRef):
            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

    def ExportSkin(self, node, armature, exportVertexArray):
        # This function exports all skinning data, which includes the skeleton
        # and per-vertex bone influence data.

        self.IndentWrite(B"Skin\n", 0, True)
        self.IndentWrite(B"{\n")
        self.indentLevel += 1

        # Write the skin bind pose transform.

        self.IndentWrite(B"Transform\n")
        self.IndentWrite(B"{\n")
        self.indentLevel += 1

        self.IndentWrite(B"float[16]\n")
        self.IndentWrite(B"{\n")
        self.WriteMatrix(node.matrix_world)
        self.IndentWrite(B"}\n")

        self.indentLevel -= 1
        self.IndentWrite(B"}\n\n")

        # Export the skeleton, which includes an array of bone node references
        # and and array of per-bone bind pose transforms.

        self.IndentWrite(B"Skeleton\n")
        self.IndentWrite(B"{\n")
        self.indentLevel += 1

        # Write the bone node reference array.

        self.IndentWrite(B"BoneRefArray\n")
        self.IndentWrite(B"{\n")
        self.indentLevel += 1

        boneArray = armature.data.bones
        boneCount = len(boneArray)

        self.IndentWrite(B"ref\t\t\t// ")
        self.WriteInt(boneCount)
        self.IndentWrite(B"{\n", 0, True)
        self.IndentWrite(B"", 1)

        for i in range(boneCount):
            boneRef = self.FindNode(boneArray[i].name)
            if (boneRef):
                self.Write(B"$")
                self.Write(boneRef[1]["structName"])
            else:
                self.Write(B"null")

            if (i < boneCount - 1):
                self.Write(B", ")
            else:
                self.Write(B"\n")

        self.IndentWrite(B"}\n")

        self.indentLevel -= 1
        self.IndentWrite(B"}\n\n")

        # Write the bind pose transform array.

        self.IndentWrite(B"Transform\n")
        self.IndentWrite(B"{\n")
        self.indentLevel += 1

        self.IndentWrite(B"float[16]\t// ")
        self.WriteInt(boneCount)
        self.IndentWrite(B"{\n", 0, True)

        for i in range(boneCount):
            self.WriteMatrixFlat(armature.matrix_world @ boneArray[i].matrix_local)
            if (i < boneCount - 1):
                self.Write(B",\n")

        self.IndentWrite(B"}\n", 0, True)

        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

        self.indentLevel -= 1
        self.IndentWrite(B"}\n\n")

        # Export the per-vertex bone influence data.

        groupRemap = []

        for group in node.vertex_groups:
            groupName = group.name
            for i in range(boneCount):
                if (boneArray[i].name == groupName):
                    groupRemap.append(i)
                    break
            else:
                groupRemap.append(-1)

        boneCountArray = []
        boneIndexArray = []
        boneWeightArray = []

        meshVertexArray = node.data.vertices
        for ev in exportVertexArray:
            boneCount = 0
            totalWeight = 0.0
            for element in meshVertexArray[ev.vertexIndex].groups:
                boneIndex = groupRemap[element.group]
                boneWeight = element.weight
                if ((boneIndex >= 0) and (boneWeight != 0.0)):
                    boneCount += 1
                    totalWeight += boneWeight
                    boneIndexArray.append(boneIndex)
                    boneWeightArray.append(boneWeight)
            boneCountArray.append(boneCount)

            if (totalWeight != 0.0):
                normalizer = 1.0 / totalWeight
                for i in range(-boneCount, 0):
                    boneWeightArray[i] *= normalizer

        # Write the bone count array. There is one entry per vertex.

        self.IndentWrite(B"BoneCountArray\n")
        self.IndentWrite(B"{\n")
        self.indentLevel += 1

        self.IndentWrite(B"unsigned_int16\t\t// ")
        self.WriteInt(len(boneCountArray))
        self.IndentWrite(B"{\n", 0, True)
        self.WriteIntArray(boneCountArray)
        self.IndentWrite(B"}\n")

        self.indentLevel -= 1
        self.IndentWrite(B"}\n\n")

        # Write the bone index array. The number of entries is the sum of the bone counts for all vertices.

        self.IndentWrite(B"BoneIndexArray\n")
        self.IndentWrite(B"{\n")
        self.indentLevel += 1

        self.IndentWrite(B"unsigned_int16\t\t// ")
        self.WriteInt(len(boneIndexArray))
        self.IndentWrite(B"{\n", 0, True)
        self.WriteIntArray(boneIndexArray)
        self.IndentWrite(B"}\n")

        self.indentLevel -= 1
        self.IndentWrite(B"}\n\n")

        # Write the bone weight array. The number of entries is the sum of the bone counts for all vertices.

        self.IndentWrite(B"BoneWeightArray\n")
        self.IndentWrite(B"{\n")
        self.indentLevel += 1

        self.IndentWrite(B"float\t\t// ")
        self.WriteInt(len(boneWeightArray))
        self.IndentWrite(B"{\n", 0, True)
        self.WriteFloatArray(boneWeightArray)
        self.IndentWrite(B"}\n")

        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

    def ExportGeometry(self, objectRef, scene):
        # This function exports a single geometry object.

        self.Write(B"\nGeometryObject $")
        self.Write(objectRef[1]["structName"])
        self.WriteNodeTable(objectRef)

        self.Write(B"\n{\n")
        self.indentLevel += 1

        node = objectRef[1]["nodeTable"][0]
        mesh = objectRef[0]

        structFlag = False

        # Save the morph state if necessary.

        activeShapeKeyIndex = node.active_shape_key_index
        showOnlyShapeKey = node.show_only_shape_key
        currentMorphValue = []

        shapeKeys = OpenGexExporter.GetShapeKeys(mesh)
        if (shapeKeys):
            node.active_shape_key_index = 0
            node.show_only_shape_key = True

            baseIndex = 0
            relative = shapeKeys.use_relative
            if (relative):
                morphCount = 0
                baseName = shapeKeys.reference_key.name
                for block in shapeKeys.key_blocks:
                    if (block.name == baseName):
                        baseIndex = morphCount
                        break
                    morphCount += 1

            morphCount = 0
            for block in shapeKeys.key_blocks:
                currentMorphValue.append(block.value)
                block.value = 0.0

                if (block.name != ""):
                    self.IndentWrite(B"Morph (index = ", 0, structFlag)
                    self.WriteInt(morphCount)

                    if ((relative) and (morphCount != baseIndex)):
                        self.Write(B", base = ")
                        self.WriteInt(baseIndex)

                    self.Write(B")\n")
                    self.IndentWrite(B"{\n")
                    self.IndentWrite(B"Name {string {\"", 1)
                    self.Write(bytes(block.name, "UTF-8"))
                    self.Write(B"\"}}\n")
                    self.IndentWrite(B"}\n")
                    structFlag = True

                morphCount += 1

            shapeKeys.key_blocks[0].value = 1.0
            mesh.update()

        self.IndentWrite(B"Mesh (primitive = \"triangles\")\n", 0, structFlag)
        self.IndentWrite(B"{\n")
        self.indentLevel += 1

        armature = node.find_armature()
        applyModifiers = (not armature)

        # Apply all modifiers to create a new mesh with tessfaces.

        # We don't apply modifiers for a skinned mesh because we need the vertex positions
        # before they are deformed by the armature modifier in order to export the proper
        # bind pose. This does mean that modifiers preceding the armature modifier are ignored,
        # but the Blender API does not provide a reasonable way to retrieve the mesh at an
        # arbitrary stage in the modifier stack.

        #exportMesh = node.to_mesh(scene, applyModifiers, "RENDER", True, False)
        #bpy.ops.view3d.select(deselect_all=True, location=(922, 599))
        #bpy.ops.object.modifier_apply

        # Apply all modifiers to create a new mesh with loop_triangles.
        exportMesh = None
        if applyModifiers:
            exportMesh = node.to_mesh()
        else:
            exportMesh = node.original.to_mesh()
        print(f"Exporting mesh with {len(mesh.vertices)} vertices at {node.matrix_world}")
        exportMesh.calc_loop_triangles()

        # Triangulate mesh and remap vertices to eliminate duplicates.

        materialTable = []
        exportVertexArray = OpenGexExporter.DeindexMesh(exportMesh, materialTable)
        triangleCount = len(materialTable)

        indexTable = []
        unifiedVertexArray = OpenGexExporter.UnifyVertices(exportVertexArray, indexTable)
        vertexCount = len(unifiedVertexArray)

        # Write the position array.

        self.IndentWrite(B"VertexArray (attrib = \"position\")\n")
        self.IndentWrite(B"{\n")
        self.indentLevel += 1

        self.IndentWrite(B"float[3]\t\t// ")
        self.WriteInt(vertexCount)
        self.IndentWrite(B"{\n", 0, True)
        self.WriteVertexArray3D(unifiedVertexArray, "position")
        self.IndentWrite(B"}\n")

        self.indentLevel -= 1
        self.IndentWrite(B"}\n\n")

        # Write the normal array.

        self.IndentWrite(B"VertexArray (attrib = \"normal\")\n")
        self.IndentWrite(B"{\n")
        self.indentLevel += 1

        self.IndentWrite(B"float[3]\t\t// ")
        self.WriteInt(vertexCount)
        self.IndentWrite(B"{\n", 0, True)
        self.WriteVertexArray3D(unifiedVertexArray, "normal")
        self.IndentWrite(B"}\n")

        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

        # Write the color array if it exists.

        colorCount = len(exportMesh.vertex_colors)
        if (colorCount > 0):
            self.IndentWrite(B"VertexArray (attrib = \"color\")\n", 0, True)
            self.IndentWrite(B"{\n")
            self.indentLevel += 1

            self.IndentWrite(B"float[3]\t\t// ")
            self.WriteInt(vertexCount)
            self.IndentWrite(B"{\n", 0, True)
            self.WriteVertexArray3D(unifiedVertexArray, "color")
            self.IndentWrite(B"}\n")

            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

        # Write the texcoord arrays.

        texcoordCount = len(exportMesh.uv_layers)
        if (texcoordCount > 0):
            self.IndentWrite(B"VertexArray (attrib = \"texcoord\")\n", 0, True)
            self.IndentWrite(B"{\n")
            self.indentLevel += 1

            self.IndentWrite(B"float[2]\t\t// ")
            self.WriteInt(vertexCount)
            self.IndentWrite(B"{\n", 0, True)
            self.WriteVertexArray2D(unifiedVertexArray, "texcoord0")
            self.IndentWrite(B"}\n")

            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

            if (texcoordCount > 1):
                self.IndentWrite(B"VertexArray (attrib = \"texcoord[1]\")\n", 0, True)
                self.IndentWrite(B"{\n")
                self.indentLevel += 1

                self.IndentWrite(B"float[2]\t\t// ")
                self.WriteInt(vertexCount)
                self.IndentWrite(B"{\n", 0, True)
                self.WriteVertexArray2D(unifiedVertexArray, "texcoord1")
                self.IndentWrite(B"}\n")

                self.indentLevel -= 1
                self.IndentWrite(B"}\n")


        # Delete the new mesh that we made earlier.

        #bpy.data.meshes.remove(exportMesh)
        node.to_mesh_clear()

        # If there are multiple morph targets, export them here.

        if (shapeKeys):
            shapeKeys.key_blocks[0].value = 0.0
            for m in range(1, len(currentMorphValue)):
                shapeKeys.key_blocks[m].value = 1.0
                mesh.update()

                node.active_shape_key_index = m
                #morphMesh = node.to_mesh(scene, applyModifiers, "RENDER", True, False)
                morphMesh = None
                if applyModifiers:
                    morphMesh = node.to_mesh()
                else:
                    morphMesh = node.original.to_mesh()
                morphMesh.calc_loop_triangles()

                # Write the morph target position array.

                self.IndentWrite(B"VertexArray (attrib = \"position\", morph = ", 0, True)
                self.WriteInt(m)
                self.Write(B")\n")
                self.IndentWrite(B"{\n")
                self.indentLevel += 1

                self.IndentWrite(B"float[3]\t\t// ")
                self.WriteInt(vertexCount)
                self.IndentWrite(B"{\n", 0, True)
                self.WriteMorphPositionArray3D(unifiedVertexArray, morphMesh.vertices)
                self.IndentWrite(B"}\n")

                self.indentLevel -= 1
                self.IndentWrite(B"}\n\n")

                # Write the morph target normal array.

                self.IndentWrite(B"VertexArray (attrib = \"normal\", morph = ")
                self.WriteInt(m)
                self.Write(B")\n")
                self.IndentWrite(B"{\n")
                self.indentLevel += 1

                self.IndentWrite(B"float[3]\t\t// ")
                self.WriteInt(vertexCount)
                self.IndentWrite(B"{\n", 0, True)
                self.WriteMorphNormalArray3D(unifiedVertexArray, morphMesh.vertices, morphMesh.loop_triangles)
                self.IndentWrite(B"}\n")

                self.indentLevel -= 1
                self.IndentWrite(B"}\n")

                #bpy.data.meshes.remove(morphMesh)
                node.to_mesh_clear()

        # Write the index arrays.
        maxMaterialIndex = 0
        for i in range(len(materialTable)):
            index = materialTable[i]
            if (index > maxMaterialIndex):
                maxMaterialIndex = index

        if (maxMaterialIndex == 0):
            # There is only one material, so write a single index array.
            self.IndentWrite(B"IndexArray\n", 0, True)
            self.IndentWrite(B"{\n")
            self.indentLevel += 1

            self.IndentWrite(B"unsigned_int32[3]\t\t// ")
            self.WriteInt(triangleCount)
            self.IndentWrite(B"{\n", 0, True)
            self.WriteTriangleArray(triangleCount, indexTable)
            self.IndentWrite(B"}\n")

            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

        else:
            # If there are multiple material indexes, then write a separate index array for each one.

            materialTriangleCount = [0 for i in range(maxMaterialIndex + 1)]
            for i in range(len(materialTable)):
                materialTriangleCount[materialTable[i]] += 1

            for m in range(maxMaterialIndex + 1):
                if (materialTriangleCount[m] != 0):
                    materialIndexTable = []
                    for i in range(len(materialTable)):
                        if (materialTable[i] == m):
                            k = i * 3
                            materialIndexTable.append(indexTable[k])
                            materialIndexTable.append(indexTable[k + 1])
                            materialIndexTable.append(indexTable[k + 2])

                    self.IndentWrite(B"IndexArray (material = ", 0, True)
                    self.WriteInt(m)
                    self.Write(B")\n")
                    self.IndentWrite(B"{\n")
                    self.indentLevel += 1

                    self.IndentWrite(B"unsigned_int32[3]\t\t// ")
                    self.WriteInt(materialTriangleCount[m])
                    self.IndentWrite(B"{\n", 0, True)
                    self.WriteTriangleArray(materialTriangleCount[m], materialIndexTable)
                    self.IndentWrite(B"}\n")

                    self.indentLevel -= 1
                    self.IndentWrite(B"}\n")

        # If the mesh is skinned, export the skinning data here.
        if (armature):
            self.ExportSkin(node, armature, unifiedVertexArray)

        # Restore the morph state.
        if (shapeKeys):
            node.active_shape_key_index = activeShapeKeyIndex
            node.show_only_shape_key = showOnlyShapeKey

            for m in range(len(currentMorphValue)):
                shapeKeys.key_blocks[m].value = currentMorphValue[m]

            mesh.update()

        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

        self.indentLevel -= 1
        self.Write(B"}\n")

    def ExportLight(self, objectRef):
        # This function exports a single light object.
        self.Write(B"\nLightObject $")
        self.Write(objectRef[1]["structName"])

        object = objectRef[0]
        type = object.type

        self.Write(B" (type = ")
        pointFlag = False
        spotFlag = False

        if (type == "SUN"):
            self.Write(B"\"infinite\"")
        elif (type == "POINT"):
            self.Write(B"\"point\"")
            pointFlag = True
        else:
            self.Write(B"\"spot\"")
            pointFlag = True
            spotFlag = True

        if (not object.use_shadow):
            self.Write(B", shadow = false")

        self.Write(B")")
        self.WriteNodeTable(objectRef)

        self.Write(B"\n{\n")
        self.indentLevel += 1

        # Export the light's color, and include a separate intensity if necessary.

        self.IndentWrite(B"Color (attrib = \"light\") {float[3] {")
        self.WriteColor(object.color)
        self.Write(B"}}\n")

        intensity = object.energy
        if (intensity != 1.0):
            self.IndentWrite(B"Param (attrib = \"intensity\") {float {")
            self.WriteFloat(intensity)
            self.Write(B"}}\n")

        if (pointFlag):
            # Export a separate attenuation function for each type that's in use.
            falloff = object.falloff_type

            if (falloff == "INVERSE_LINEAR"):
                self.IndentWrite(B"Atten (curve = \"inverse\")\n", 0, True)
                self.IndentWrite(B"{\n")

                self.IndentWrite(B"Param (attrib = \"scale\") {float {", 1)
                self.WriteFloat(object.distance)
                self.Write(B"}}\n")

                self.IndentWrite(B"}\n")

            elif (falloff == "INVERSE_SQUARE"):
                self.IndentWrite(B"Atten (curve = \"inverse_square\")\n", 0, True)
                self.IndentWrite(B"{\n")

                self.IndentWrite(B"Param (attrib = \"scale\") {float {", 1)
                self.WriteFloat(math.sqrt(object.distance))
                self.Write(B"}}\n")

                self.IndentWrite(B"}\n")

            elif (falloff == "LINEAR_QUADRATIC_WEIGHTED"):
                if (object.linear_attenuation != 0.0):
                    self.IndentWrite(B"Atten (curve = \"inverse\")\n", 0, True)
                    self.IndentWrite(B"{\n")

                    self.IndentWrite(B"Param (attrib = \"scale\") {float {", 1)
                    self.WriteFloat(object.distance)
                    self.Write(B"}}\n")

                    self.IndentWrite(B"Param (attrib = \"constant\") {float {", 1)
                    self.WriteFloat(1.0)
                    self.Write(B"}}\n")

                    self.IndentWrite(B"Param (attrib = \"linear\") {float {", 1)
                    self.WriteFloat(object.linear_attenuation)
                    self.Write(B"}}\n")

                    self.IndentWrite(B"}\n\n")

                if (object.quadratic_attenuation != 0.0):
                    self.IndentWrite(B"Atten (curve = \"inverse_square\")\n")
                    self.IndentWrite(B"{\n")

                    self.IndentWrite(B"Param (attrib = \"scale\") {float {", 1)
                    self.WriteFloat(object.distance)
                    self.Write(B"}}\n")

                    self.IndentWrite(B"Param (attrib = \"constant\") {float {", 1)
                    self.WriteFloat(1.0)
                    self.Write(B"}}\n")

                    self.IndentWrite(B"Param (attrib = \"quadratic\") {float {", 1)
                    self.WriteFloat(object.quadratic_attenuation)
                    self.Write(B"}}\n")

                    self.IndentWrite(B"}\n")

            # if (object.use_sphere):
            #     self.IndentWrite(B"Atten (curve = \"linear\")\n", 0, True)
            #     self.IndentWrite(B"{\n")

            #     self.IndentWrite(B"Param (attrib = \"end\") {float {", 1)
            #     self.WriteFloat(object.distance)
            #     self.Write(B"}}\n")

            #     self.IndentWrite(B"}\n")

            if (spotFlag):

                # Export additional angular attenuation for spot lights.

                self.IndentWrite(B"Atten (kind = \"angle\", curve = \"linear\")\n", 0, True)
                self.IndentWrite(B"{\n")

                endAngle = object.spot_size * 0.5
                beginAngle = endAngle * (1.0 - object.spot_blend)

                self.IndentWrite(B"Param (attrib = \"begin\") {float {", 1)
                self.WriteFloat(beginAngle)
                self.Write(B"}}\n")

                self.IndentWrite(B"Param (attrib = \"end\") {float {", 1)
                self.WriteFloat(endAngle)
                self.Write(B"}}\n")

                self.IndentWrite(B"}\n")

        self.indentLevel -= 1
        self.Write(B"}\n")

    def ExportCamera(self, objectRef):
        # This function exports a single camera object.
        self.Write(B"\nCameraObject $")
        self.Write(objectRef[1]["structName"])
        self.WriteNodeTable(objectRef)

        self.Write(B"\n{\n")
        self.indentLevel += 1

        object = objectRef[0]

        self.IndentWrite(B"Param (attrib = \"fov\") {float {")
        self.WriteFloat(object.angle_x)
        self.Write(B"}}\n")

        self.IndentWrite(B"Param (attrib = \"near\") {float {")
        self.WriteFloat(object.clip_start)
        self.Write(B"}}\n")

        self.IndentWrite(B"Param (attrib = \"far\") {float {")
        self.WriteFloat(object.clip_end)
        self.Write(B"}}\n")

        self.indentLevel -= 1
        self.Write(B"}\n")

    def ExportObjects(self, scene):
        for objectRef in self.geometryArray.items():
            self.ExportGeometry(objectRef, scene)
        for objectRef in self.lightArray.items():
            self.ExportLight(objectRef)
        for objectRef in self.cameraArray.items():
            self.ExportCamera(objectRef)

    def ExportTexture(self, textureSlot, attrib):
        # This function exports a single texture from a material.
        self.IndentWrite(B"Texture (attrib = \"", 0, True)
        self.Write(attrib)
        self.Write(B"\")\n")

        self.IndentWrite(B"{\n")
        self.indentLevel += 1

        self.IndentWrite(B"string {\"")
        self.WriteFileName(textureSlot.texture.image.filepath)
        self.Write(B"\"}\n")

        # TODO(dlb): Do these props still exist in 2.8? If not, check how glTF finds texture transforms
        # If the texture has a scale and/or offset, then export a coordinate transform.
        uscale = textureSlot.scale[0]
        vscale = textureSlot.scale[1]
        uoffset = textureSlot.offset[0]
        voffset = textureSlot.offset[1]

        if ((uscale != 1.0) or (vscale != 1.0) or (uoffset != 0.0) or (voffset != 0.0)):
            matrix = [[uscale, 0.0, 0.0, 0.0], [0.0, vscale, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [uoffset, voffset, 0.0, 1.0]]

            self.IndentWrite(B"Transform\n", 0, True)
            self.IndentWrite(B"{\n")
            self.indentLevel += 1

            self.IndentWrite(B"float[16]\n")
            self.IndentWrite(B"{\n")
            self.WriteMatrix(matrix)
            self.IndentWrite(B"}\n")

            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

    def ExportMaterials(self):
        # This function exports all of the materials used in the scene.
        for materialRef in self.materialArray.items():
            material = materialRef[0]

            self.Write(B"\nMaterial $")
            self.Write(materialRef[1]["structName"])
            self.Write(B"\n{\n")
            self.indentLevel += 1

            if (material.name != ""):
                self.IndentWrite(B"Name {string {\"")
                self.Write(bytes(material.name, "UTF-8"))
                self.Write(B"\"}}\n\n")

            print("Blender material nodes:")
            for n in material.node_tree.nodes:
                print(f"  {n}")

            # TODO: Do we want to support factor + texture? We would have to figure out how to extract that from the node tree
            # If diffuse texture is connected, set factor to all ones
            # NOTE(dlb): Taken from gltf2_blender_gather_materials() and gltf2_blender_gather_materials_pbr_metallic_roughness()
            #alpha_cutoff               = gather_alpha_cutoff(material)
            #alpha_mode                 = gather_alpha_mode(material)
            base_color_factor          = gather_base_color_factor(material)
            base_color_texture         = gather_base_color_texture(material)
            emissive_factor            = gather_emissive_factor(material)
            emissive_texture           = gather_emissive_texture(material)
            metallic_factor            = gather_metallic_factor(material)
            metallic_roughness_texture = gather_metallic_roughness_texture(material)
            normal_texture             = gather_normal_texture(material)
            #occlusion_texture          = gather_occlusion_texture(material)
            roughness_factor           = gather_roughness_factor(material)

            self.IndentWrite(B"Color (attrib = \"diffuse\") {float[3] {")
            self.WriteColor(diffuse)
            self.Write(B"}}\n")

            self.IndentWrite(B"Color (attrib = \"emission\") {float[3] {")
            self.WriteColor(emission)
            self.Write(B"}}\n")

            # TODO(dlb): Export factors if textures don't exist? Or both? Mix? Something?
            if (base_color_texture):
                self.ExportTexture(base_color_texture, B"diffuse")
            if (emissive_texture):
                self.ExportTexture(emissive_texture, B"emission")
            if (metallic_roughness_texture):
                self.ExportTexture(metallic_roughness_texture, B"metallic_roughness")
            if (normal_texture):
                self.ExportTexture(normal_texture, B"normal")

            self.indentLevel -= 1
            self.Write(B"}\n")

    def ExportMetrics(self, scene):
        scale = scene.unit_settings.scale_length

        if (scene.unit_settings.system == "IMPERIAL"):
            scale *= 0.3048

        self.Write(B"Metric (key = \"distance\") {float {")
        self.WriteFloat(scale)
        self.Write(B"}}\n")

        self.Write(B"Metric (key = \"angle\") {float {")
        self.WriteFloat(1.0)
        self.Write(B"}}\n")
        self.Write(B"Metric (key = \"time\") {float {")
        self.WriteFloat(1.0)
        self.Write(B"}}\n")
        self.Write(B"Metric (key = \"up\") {string {\"z\"}}\n")

    def execute(self, context):
        print("\n#--------------------------------------------------")
        print("# OpenGEX Exporter v0.0.0")
        print("#--------------------------------------------------")

        self.file = open(self.filepath, "wb")

        self.indentLevel = 0

        scene = context.scene
        print("ExportMetrics")
        self.ExportMetrics(scene)

        originalFrame = scene.frame_current
        originalSubframe = scene.frame_subframe
        self.restoreFrame = False

        self.beginFrame = scene.frame_start
        self.endFrame = scene.frame_end
        self.frameTime = 1.0 / (scene.render.fps_base * scene.render.fps)

        self.nodeArray = {}
        self.geometryArray = {}
        self.lightArray = {}
        self.cameraArray = {}
        self.materialArray = {}
        self.boneParentArray = {}

        self.exportAllFlag = not self.option_export_selection
        self.sampleAnimationFlag = self.option_sample_animation

        for object in scene.objects:
            if (not object.parent):
                print(f"ProcessNode: {object.type} {object.name}")
                self.ProcessNode(object)

        self.ProcessSkinnedMeshes()

        for object in scene.objects:
            if (not object.parent):
                print(f"ExportNode: {object.type} {object.name}")
                self.ExportNode(object, scene)

        print("ExportObjects")
        self.ExportObjects(scene)
        print("ExportMaterials")
        self.ExportMaterials()

        if (self.restoreFrame):
            scene.frame_set(originalFrame, subframe=originalSubframe)

        self.file.close()
        print("Finished")
        return {'FINISHED'}

def menu_func(self, context):
    self.layout.operator(OpenGexExporter.bl_idname, text = "OpenGEX (.ogex)")

def register():
    bpy.utils.register_class(OpenGexExporter)
    bpy.types.TOPBAR_MT_file_export.append(menu_func)

def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(menu_func)
    bpy.utils.unregister_class(OpenGexExporter)

if __name__ == "__main__":
    register()








class Image:
    def __init__(self, buffer_view, extensions, extras, mime_type, name, uri):
        self.buffer_view = buffer_view
        self.extensions = extensions
        self.extras = extras
        self.mime_type = mime_type
        self.name = name
        self.uri = uri

class ImageData:
    def __init__(self, data: bytes, mime_type: str, name: str):
        self._data = data
        self._mime_type = mime_type
        self._name = name

    def __eq__(self, other):
        return self._data == other.data

    def __hash__(self):
        return hash(self._data)

    def adjusted_name(self):
        regex_dot = re.compile("\.")
        adjusted_name = re.sub(regex_dot, "_", self.name)
        new_name = "".join([char for char in adjusted_name if char not in "!#$&'()*+,/:;<>?@[\]^`{|}~"])
        return new_name

    @property
    def data(self):
        return self._data

    @property
    def name(self):
        return self._name

    @property
    def file_extension(self):
        if self._mime_type == "image/jpeg":
            return ".jpg"
        return ".png"

    @property
    def byte_length(self):
        return len(self._data)

class MaterialNormalTextureInfoClass:
    def __init__(self, extensions, extras, index, scale, tex_coord):
        self.index = index
        self.scale = scale
        self.tex_coord = tex_coord

class Sampler:
    def __init__(self, extensions, extras, mag_filter, min_filter, name, wrap_s, wrap_t):
        self.extensions = extensions
        self.extras = extras
        self.mag_filter = mag_filter
        self.min_filter = min_filter
        self.name = name
        self.wrap_s = wrap_s
        self.wrap_t = wrap_t

class Texture:
    def __init__(self, extensions, extras, name, sampler, source):
        self.extensions = extensions
        self.extras = extras
        self.name = name
        self.sampler = sampler
        self.source = source

class TextureInfo:
    def __init__(self, extensions, extras, index, tex_coord):
        self.index = index
        self.tex_coord = tex_coord





def print_console(level, output):
    current_time = time.gmtime()
    ts = time.strftime("%H:%M:%S", current_time)
    print(ts + " | " + level + ': ' + output)

# material.node_tree.nodes["Principled BSDF"].inputs
# --------------------------------------------------
# <bpy_struct, NodeSocketColor       ("Base Color")>
# <bpy_struct, NodeSocketFloatFactor ("Subsurface")>
# <bpy_struct, NodeSocketVector      ("Subsurface Radius")>
# <bpy_struct, NodeSocketColor       ("Subsurface Color")>
# <bpy_struct, NodeSocketFloatFactor ("Metallic")>
# <bpy_struct, NodeSocketFloatFactor ("Specular")>
# <bpy_struct, NodeSocketFloatFactor ("Specular Tint")>
# <bpy_struct, NodeSocketFloatFactor ("Roughness")>
# <bpy_struct, NodeSocketFloatFactor ("Anisotropic")>
# <bpy_struct, NodeSocketFloatFactor ("Anisotropic Rotation")>
# <bpy_struct, NodeSocketFloatFactor ("Sheen")>
# <bpy_struct, NodeSocketFloatFactor ("Sheen Tint")>
# <bpy_struct, NodeSocketFloatFactor ("Clearcoat")>
# <bpy_struct, NodeSocketFloatFactor ("Clearcoat Roughness")>
# <bpy_struct, NodeSocketFloat       ("IOR")>
# <bpy_struct, NodeSocketFloatFactor ("Transmission")>
# <bpy_struct, NodeSocketFloatFactor ("Transmission Roughness")>
# <bpy_struct, NodeSocketColor       ("Emission")>
# <bpy_struct, NodeSocketFloatFactor ("Alpha")>
# <bpy_struct, NodeSocketVector      ("Normal")>
# <bpy_struct, NodeSocketVector      ("Clearcoat Normal")>
# <bpy_struct, NodeSocketVector      ("Tangent")>
def get_socket_or_texture_slot(blender_material: bpy.types.Material, name: str):
    """
    For a given material input name, retrieve the corresponding node tree socket.

    :param blender_material: a blender material for which to get the socket/slot
    :param name: the name of the socket
    :return: a blender NodeSocket, if the material is a node tree
    """
    if blender_material.node_tree and blender_material.use_nodes:
        type = bpy.types.ShaderNodeBsdfPrincipled
        nodes = [n for n in blender_material.node_tree.nodes if isinstance(n, type)]
        inputs = sum([[input for input in node.inputs if input.name == name] for node in nodes], [])
        if inputs:
            return inputs[0]

    return None





#def gather_alpha_cutoff(blender_material):
#    if blender_material.blend_method == 'CLIP':
#        return blender_material.alpha_threshold
#    return None
#
#def gather_alpha_mode(blender_material):
#    if blender_material.blend_method == 'CLIP':
#        return 'MASK'
#    elif blender_material.blend_method == 'BLEND':
#        return 'BLEND'
#    return None

def gather_emissive_factor(blender_material):
    emissive_socket = get_socket_or_texture_slot(blender_material, "Emissive")
    if isinstance(emissive_socket, bpy.types.NodeSocket):
        if emissive_socket.is_linked:
            # In glTF, the default emissiveFactor is all zeros, so if an emission texture is connected,
            # we have to manually set it to all ones.
            return [1.0, 1.0, 1.0]
        else:
            return list(emissive_socket.default_value)[0:3]
    return None

def gather_emissive_texture(blender_material):
    emissive = get_socket_or_texture_slot(blender_material, "Emissive")
    return gather_texture_info(emissive)

def gather_normal_texture(blender_material):
    normal = get_socket_or_texture_slot(blender_material, "Normal")
    return gather_material_normal_texture_info_class(normal)

# def gather_occlusion_texture(blender_material):
#     occlusion = get_socket_or_texture_slot(blender_material, "Occlusion")
#     if occlusion is None:
#         occlusion = get_socket_or_texture_slot_old(blender_material, "Occlusion")
#     return gltf2_blender_gather_material_occlusion_texture_info_class.gather_material_occlusion_texture_info_class(
#         (occlusion,))

def has_image_node_from_socket(socket):
    result = from_socket(socket, bpy.types.ShaderNodeTexImage)
    if not result:
        return False
    return True





def gather_base_color_factor(blender_material):
    base_color_socket = get_socket_or_texture_slot(blender_material, "Base Color")
    if not isinstance(base_color_socket, bpy.types.NodeSocket):
        return None
    if not base_color_socket.is_linked:
        return list(base_color_socket.default_value)

    texture_node = get_tex_from_socket(base_color_socket)
    if texture_node is None:
        return None

    def is_valid_multiply_node(node):
        return isinstance(node, bpy.types.ShaderNodeMixRGB) and \
            node.blend_type == "MULTIPLY" and \
            len(node.inputs) == 3

    multiply_node = next((link.from_node for link in texture_node.path if is_valid_multiply_node(link.from_node)), None)
    if multiply_node is None:
        return None

    def is_factor_socket(socket):
        return isinstance(socket, bpy.types.NodeSocketColor) and \
            (not socket.is_linked or socket.links[0] not in texture_node.path)

    factor_socket = next((socket for socket in multiply_node.inputs if is_factor_socket(socket)), None)
    if factor_socket is None:
        return None

    if factor_socket.is_linked:
        print_console("WARNING", "BaseColorFactor only supports sockets without links (in Node '{}')."
                    .format(multiply_node.name))
        return None

    return list(factor_socket.default_value)

def gather_base_color_texture(blender_material):
    base_color_socket = get_socket_or_texture_slot(blender_material, "Base Color")

    alpha_socket = get_socket_or_texture_slot(blender_material, "Alpha")
    if alpha_socket is not None and alpha_socket.is_linked:
        inputs = (base_color_socket, alpha_socket, )
    else:
        inputs = (base_color_socket,)

    return gather_texture_info(inputs)

def get_tex_from_socket(blender_shader_socket: bpy.types.NodeSocket):
    result = from_socket(blender_shader_socket, bpy.types.ShaderNodeTexImage)
    if not result:
        return None
    return result[0]

def gather_metallic_factor(blender_material):
    metallic_socket = get_socket_or_texture_slot(blender_material, "Metallic")
    if isinstance(metallic_socket, bpy.types.NodeSocket) and not metallic_socket.is_linked:
        return metallic_socket.default_value
    return None

def gather_metallic_roughness_texture(blender_material):
    metallic_socket = get_socket_or_texture_slot(blender_material, "Metallic")
    roughness_socket = get_socket_or_texture_slot(blender_material, "Roughness")

    hasMetal = metallic_socket is not None and has_image_node_from_socket(metallic_socket)
    hasRough = roughness_socket is not None and has_image_node_from_socket(roughness_socket)

    if not hasMetal and not hasRough:
        return None
    elif not hasMetal:
        texture_input = (roughness_socket,)
    elif not hasRough:
        texture_input = (metallic_socket,)
    else:
        texture_input = (metallic_socket, roughness_socket)

    return gather_texture_info(texture_input)

def gather_roughness_factor(blender_material):
    roughness_socket = get_socket_or_texture_slot(blender_material, "Roughness")
    if isinstance(roughness_socket, bpy.types.NodeSocket) and not roughness_socket.is_linked:
        return roughness_socket.default_value
    return None

def has_image_node_from_socket(socket):
    result = from_socket(socket, bpy.types.ShaderNodeTexImage)
    if not result:
        return False
    return True





def gather_texture_info(blender_shader_sockets_or_texture_slots: typing.Union[
    typing.Tuple[bpy.types.NodeSocket], typing.Tuple[bpy.types.Texture]]):
    if not filter_texture_info(blender_shader_sockets_or_texture_slots):
        return None

    texture_info = TextureInfo(
        index=gather_texture(blender_shader_sockets_or_texture_slots),
        tex_coord=gather_tex_coord(blender_shader_sockets_or_texture_slots)
    )

    if texture_info.index is None:
        return None

    return texture_info

def filter_texture_info(blender_shader_sockets_or_texture_slots):
    if not blender_shader_sockets_or_texture_slots:
        return False
    if not all([elem is not None for elem in blender_shader_sockets_or_texture_slots]):
        return False
    if isinstance(blender_shader_sockets_or_texture_slots[0], bpy.types.NodeSocket):
        if any([get_tex_from_socket(socket) is None for socket in blender_shader_sockets_or_texture_slots]):
            # sockets do not lead to a texture --> discard
            return False

        resolution = get_tex_from_socket(blender_shader_sockets_or_texture_slots[0]).shader_node.image.size
        if any(any(a != b for a, b in zip(get_tex_from_socket(elem).shader_node.image.size, resolution))
            for elem in blender_shader_sockets_or_texture_slots):
            def format_image(image_node):
                return "{} ({}x{})".format(image_node.image.name, image_node.image.size[0], image_node.image.size[1])

            images = [format_image(get_tex_from_socket(elem).shader_node) for elem in
                    blender_shader_sockets_or_texture_slots]

            print_console("ERROR", "Image sizes do not match. In order to be merged into one image file, "
                                "images need to be of the same size. Images: {}".format(images))
            return False

    return True

def gather_tex_coord(blender_shader_sockets_or_texture_slots):
    if isinstance(blender_shader_sockets_or_texture_slots[0], bpy.types.NodeSocket):
        blender_shader_node = get_tex_from_socket(blender_shader_sockets_or_texture_slots[0]).shader_node
        if len(blender_shader_node.inputs['Vector'].links) == 0:
            return 0

        input_node = blender_shader_node.inputs['Vector'].links[0].from_node

        if isinstance(input_node, bpy.types.ShaderNodeMapping):

            if len(input_node.inputs['Vector'].links) == 0:
                return 0

            input_node = input_node.inputs['Vector'].links[0].from_node

        if not isinstance(input_node, bpy.types.ShaderNodeUVMap):
            return 0

        if input_node.uv_map == '':
            return 0

        # Try to gather map index.
        for blender_mesh in bpy.data.meshes:
            texCoordIndex = blender_mesh.uv_layers.find(input_node.uv_map)
            if texCoordIndex >= 0:
                return texCoordIndex

        return 0
    elif isinstance(blender_shader_sockets_or_texture_slots[0], bpy.types.MaterialTextureSlot):
        # TODO: implement for texture slots
        return 0
    else:
        raise NotImplementedError()

def get_tex_from_socket(socket):
    result = from_socket(socket, bpy.types.ShaderNodeTexImage)
    if not result:
        return None
    if result[0].shader_node.image is None:
        return None
    return result[0]





def gather_material_normal_texture_info_class(blender_shader_sockets_or_texture_slots: typing.Union[
    typing.Tuple[bpy.types.NodeSocket], typing.Tuple[bpy.types.Texture]]):
    if not normal_filter_texture_info(blender_shader_sockets_or_texture_slots):
        return None

    texture_info = MaterialNormalTextureInfoClass(
        scale=normal_gather_scale(blender_shader_sockets_or_texture_slots),
        index=gather_texture(blender_shader_sockets_or_texture_slots),
        tex_coord=normal_gather_tex_coord(blender_shader_sockets_or_texture_slots)
    )

    if texture_info.index is None:
        return None

    return texture_info

def normal_filter_texture_info(blender_shader_sockets_or_texture_slots):
    if not blender_shader_sockets_or_texture_slots:
        return False
    if not all([elem is not None for elem in blender_shader_sockets_or_texture_slots]):
        return False
    if isinstance(blender_shader_sockets_or_texture_slots[0], bpy.types.NodeSocket):
        if any([get_tex_from_socket(socket) is None for socket in blender_shader_sockets_or_texture_slots]):
            # sockets do not lead to a texture --> discard
            return False
    return True

def normal_gather_extensions(blender_shader_sockets_or_texture_slots):
    if not hasattr(blender_shader_sockets_or_texture_slots[0], 'links'):
        return None

    tex_nodes = [get_tex_from_socket(socket).shader_node for socket in blender_shader_sockets_or_texture_slots]
    texture_node = tex_nodes[0] if (tex_nodes is not None and len(tex_nodes) > 0) else None
    if texture_node is None:
        return None
    texture_transform = gltf2_blender_get.get_texture_transform_from_texture_node(texture_node)
    if texture_transform is None:
        return None

    extension = Extension("KHR_texture_transform", texture_transform)
    return {"KHR_texture_transform": extension}

def normal_gather_extras(blender_shader_sockets_or_texture_slots):
    return None

def normal_gather_scale(blender_shader_sockets_or_texture_slots):
    if isinstance(blender_shader_sockets_or_texture_slots[0], bpy.types.NodeSocket):
        result = from_socket(
            blender_shader_sockets_or_texture_slots[0],
            bpy.types.ShaderNodeNormalMap)
        if not result:
            return None
        strengthInput = result[0].shader_node.inputs['Strength']
        if not strengthInput.is_linked and strengthInput.default_value != 1:
            return strengthInput.default_value
    return None

def normal_gather_tex_coord(blender_shader_sockets_or_texture_slots):
    if isinstance(blender_shader_sockets_or_texture_slots[0], bpy.types.NodeSocket):
        blender_shader_node = get_tex_from_socket(blender_shader_sockets_or_texture_slots[0]).shader_node
        if len(blender_shader_node.inputs['Vector'].links) == 0:
            return 0

        input_node = blender_shader_node.inputs['Vector'].links[0].from_node

        if isinstance(input_node, bpy.types.ShaderNodeMapping):

            if len(input_node.inputs['Vector'].links) == 0:
                return 0

            input_node = input_node.inputs['Vector'].links[0].from_node

        if not isinstance(input_node, bpy.types.ShaderNodeUVMap):
            return 0

        if input_node.uv_map == '':
            return 0

        # Try to gather map index.
        for blender_mesh in bpy.data.meshes:
            if bpy.app.version < (2, 80, 0):
                texCoordIndex = blender_mesh.uv_textures.find(input_node.uv_map)
            else:
                texCoordIndex = blender_mesh.uv_layers.find(input_node.uv_map)
            if texCoordIndex >= 0:
                return texCoordIndex

        return 0
    else:
        raise NotImplementedError()





class NodeTreeSearchResult:
    def __init__(self, shader_node: bpy.types.Node, path: typing.List[bpy.types.NodeLink]):
        self.shader_node = shader_node
        self.path = path

# TODO: cache these searches
def from_socket(start_socket: bpy.types.NodeSocket, shader_node_filter_type) -> typing.List[NodeTreeSearchResult]:
    """
    Find shader nodes where the filter expression is true.

    :param start_socket: the beginning of the traversal
    :param shader_node_filter_type: should be a type to match node against
    :return: a list of shader nodes for which filter is true
    """
    # hide implementation (especially the search path)
    def __search_from_socket(start_socket: bpy.types.NodeSocket,
                            shader_node_filter_type,
                            search_path: typing.List[bpy.types.NodeLink]) -> typing.List[NodeTreeSearchResult]:
        results = []

        for link in start_socket.links:
            # follow the link to a shader node
            linked_node = link.from_node
            # check if the node matches the filter
            if isinstance(linked_node, shader_node_filter_type):
                results.append(NodeTreeSearchResult(linked_node, search_path + [link]))
            # traverse into inputs of the node
            for input_socket in linked_node.inputs:
                linked_results = __search_from_socket(input_socket, shader_node_filter_type, search_path + [link])
                if linked_results:
                    # add the link to the current path
                    search_path.append(link)
                    results += linked_results

        return results

    if start_socket is None:
        return []

    return __search_from_socket(start_socket, shader_node_filter_type, [])





def gather_texture(
        blender_shader_sockets_or_texture_slots: typing.Union[
            typing.Tuple[bpy.types.NodeSocket], typing.Tuple[typing.Any]]):
    """
    Gather texture sampling information and image channels from a blender shader texture attached to a shader socket.

    :param blender_shader_sockets: The sockets of the material which should contribute to the texture
    :return: a glTF 2.0 texture with sampler and source embedded (will be converted to references by the exporter)
    """
    texture = Texture(
        name=None,
        sampler=gather_texture_sampler(blender_shader_sockets_or_texture_slots),
        source=gather_texture_source(blender_shader_sockets_or_texture_slots)
    )

    # although valid, most viewers can't handle missing source properties
    if texture.source is None:
        return None

    return texture

def gather_texture_sampler(blender_shader_sockets_or_texture_slots):
    if isinstance(blender_shader_sockets_or_texture_slots[0], bpy.types.NodeSocket):
        def gather_texture_from_socket(socket):
            result = from_socket(socket, bpy.types.ShaderNodeTexImage)
            if not result:
                return None
            return result[0]

        shader_nodes = [gather_texture_from_socket(socket).shader_node for socket in blender_shader_sockets_or_texture_slots]
        if len(shader_nodes) > 1:
            print_console("WARNING",
                          "More than one shader node tex image used for a texture. "
                          "The resulting glTF sampler will behave like the first shader node tex image.")
        return gather_sampler(shader_nodes[0])
    elif isinstance(blender_shader_sockets_or_texture_slots[0], bpy.types.MaterialTextureSlot):
        return gather_sampler_from_texture_slot(blender_shader_sockets_or_texture_slots[0])
    else:
        # TODO: implement texture slot sampler
        raise NotImplementedError()

def gather_texture_source(blender_shader_sockets_or_texture_slots):
    return gather_image(blender_shader_sockets_or_texture_slots)





def gather_sampler(blender_shader_node: bpy.types.Node):
    if not gather_sampler_filter(blender_shader_node):
        return None

    sampler = Sampler(
        mag_filter=gather_sampler_mag_filter(blender_shader_node),
        min_filter=gather_sampler_min_filter(blender_shader_node),
        name=None,
        wrap_s=gather_sampler_wrap_s(blender_shader_node),
        wrap_t=gather_sampler_wrap_t(blender_shader_node)
    )

    return sampler

def gather_sampler_filter(blender_shader_node):
    if not blender_shader_node.interpolation == 'Closest' and not blender_shader_node.extension == 'CLIP':
        return False
    return True

def gather_sampler_mag_filter(blender_shader_node):
    if blender_shader_node.interpolation == 'Closest':
        return 9728  # NEAREST
    return 9729  # LINEAR

def gather_sampler_min_filter(blender_shader_node):
    if blender_shader_node.interpolation == 'Closest':
        return 9984  # NEAREST_MIPMAP_NEAREST
    return 9986  # NEAREST_MIPMAP_LINEAR

def gather_sampler_wrap_s(blender_shader_node):
    if blender_shader_node.extension == 'EXTEND':
        return 33071
    return None

def gather_sampler_wrap_t(blender_shader_node):
    if blender_shader_node.extension == 'EXTEND':
        return 33071
    return None

def gather_sampler_from_texture_slot(blender_texture: bpy.types.TextureSlot):
    magFilter = 9729
    wrap = 10497
    if blender_texture.texture.extension == 'EXTEND':
        wrap = 33071

    minFilter = 9986
    if magFilter == 9728:
        minFilter = 9984

    return Sampler(
        mag_filter=magFilter,
        min_filter=minFilter,
        name=None,
        wrap_s=wrap,
        wrap_t=wrap
    )





def gather_image(
        blender_shader_sockets_or_texture_slots: typing.Union[typing.Tuple[bpy.types.NodeSocket],
                                                              typing.Tuple[bpy.types.Texture]]):
    if not gather_image_filter(blender_shader_sockets_or_texture_slots):
        return None

    image_data = gather_image_data(blender_shader_sockets_or_texture_slots)
    if image_data.empty():
        # The export image has no data
        return None

    image = Image(
        buffer_view=gather_image_buffer_view(image_data, mime_type, name),
        mime_type="image/png",
        name=gather_image_name(blender_shader_sockets_or_texture_slots),
        uri=gather_image_uri(image_data, mime_type, name)
    )

    return image

def gather_image_filter(sockets_or_slots):
    if not sockets_or_slots:
        return False
    return True

def gather_image_buffer_view(image_data, mime_type, name):
    # TODO(dlb): Separate vs. embedded images?
    # if export_settings[gltf2_blender_export_keys.FORMAT] != 'GLTF_SEPARATE':
    #     return gltf2_io_binary_data.BinaryData(data=image_data.encode(mime_type))
    return None

def gather_image_name(sockets_or_slots):
    if isinstance(sockets_or_slots[0], bpy.types.NodeSocket):
        combined_name = None
        foundNames = []
        # If multiple images are being combined, combine the names as well.
        for socket in sockets_or_slots:
            node = get_tex_from_socket(socket)
            if node is not None:
                image_name = node.shader_node.image.name
                if image_name not in foundNames:
                    foundNames.append(image_name)
                    name, extension = os.path.splitext(image_name)
                    if combined_name is None:
                        combined_name = name
                    else:
                        combined_name += '-' + name

        # If only one image was used, and that image has a real filepath, use the real filepath instead.
        if len(foundNames) == 1:
            filename = os.path.basename(bpy.data.images[foundNames[0]].filepath)
            name, extension = os.path.splitext(filename)
            if extension.lower() in ['.png', '.jpg', '.jpeg']:
                return name

        return combined_name

    elif isinstance(sockets_or_slots[0], bpy.types.MaterialTextureSlot):
        return sockets_or_slots[0].texture.image.name

def gather_image_uri(image_data, mime_type, name):
    # TODO(dlb): Separate vs. embedded images?
    #if export_settings[gltf2_blender_export_keys.FORMAT] == 'GLTF_SEPARATE':
    if True:
        # as usual we just store the data in place instead of already resolving the references
        return ImageData(
            data=image_data.encode(mime_type=mime_type),
            mime_type=mime_type,
            name=name
        )

    return None

def gather_image_data(sockets_or_slots) -> ExportImage:
    # For shared resources, such as images, we just store the portion of data that is needed in the glTF property
    # in a helper class. During generation of the glTF in the exporter these will then be combined to actual binary
    # resources.
    if isinstance(sockets_or_slots[0], bpy.types.NodeSocket):
        results = [get_tex_from_socket(socket) for socket in sockets_or_slots]
        composed_image = ExportImage()
        for result, socket in zip(results, sockets_or_slots):
            if result.shader_node.image.channels == 0:
                gltf2_io_debug.print_console("WARNING",
                                             "Image '{}' has no color channels and cannot be exported.".format(
                                                 result.shader_node.image))
                continue

            # rudimentarily try follow the node tree to find the correct image data.
            src_chan = Channel.R
            for elem in result.path:
                if isinstance(elem.from_node, bpy.types.ShaderNodeSeparateRGB):
                   src_chan = {
                        'R': Channel.R,
                        'G': Channel.G,
                        'B': Channel.B,
                    }[elem.from_socket.name]
                if elem.from_socket.name == 'Alpha':
                    src_chan = Channel.A

            dst_chan = None

            # some sockets need channel rewriting (gltf pbr defines fixed channels for some attributes)
            if socket.name == 'Metallic':
                dst_chan = Channel.B
            elif socket.name == 'Roughness':
                dst_chan = Channel.G
            elif socket.name == 'Occlusion' and len(sockets_or_slots) > 1 and sockets_or_slots[1] is not None:
                dst_chan = Channel.R
            elif socket.name == 'Alpha' and len(sockets_or_slots) > 1 and sockets_or_slots[1] is not None:
                dst_chan = Channel.A

            if dst_chan is not None:
                composed_image.fill_image(result.shader_node.image, dst_chan, src_chan)

                # Since metal/roughness are always used together, make sure
                # the other channel is filled.
                if socket.name == 'Metallic' and not composed_image.is_filled(Channel.G):
                    composed_image.fill_white(Channel.G)
                elif socket.name == 'Roughness' and not composed_image.is_filled(Channel.B):
                    composed_image.fill_white(Channel.B)
            else:
                # copy full image...eventually following sockets might overwrite things
                composed_image = ExportImage.from_blender_image(result.shader_node.image)

        return composed_image

    elif isinstance(sockets_or_slots[0], bpy.types.MaterialTextureSlot):
        texture = sockets_or_slots[0].texture
        image = ExportImage.from_blender_image(texture.image)
        return image
    else:
        raise NotImplementedError()


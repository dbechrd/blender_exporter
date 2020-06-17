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
import enum
import logging
import math
import os
import re
import struct
import tempfile
import time
import typing
from typing import Optional
from bpy_extras.io_utils import ExportHelper

log = logging.getLogger(__name__)
kOutputColumns = 32

kNodeTypeNode = 0
kNodeTypeBone = 1
kNodeTypeGeometry = 2
kNodeTypeLight = 3
kNodeTypeCamera = 4

kAnimationSampled = 0
kAnimationLinear = 1
kAnimationBezier = 2

kExportEpsilon = 1.0e-6

structIdentifier = [B"node", B"bone_node", B"geometry_node", B"light_node", B"camera_node"]

subtranslationName = [B"xpos", B"ypos", B"zpos"]
subrotationName = [B"xrot", B"yrot", B"zrot"]
subscaleName = [B"xscl", B"yscl", B"zscl"]
deltaSubtranslationName = [B"dxpos", B"dypos", B"dzpos"]
deltaSubrotationName = [B"dxrot", B"dyrot", B"dzrot"]
deltaSubscaleName = [B"dxscl", B"dyscl", B"dzscl"]
axisName = [B"x", B"y", B"z"]

class ExportVertex:
    __slots__ = ("hash", "vertexIndex", "faceIndex", "position", "normal", "tangent", "color", "texcoord0", "texcoord1")

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
        if (self.tangent != v.tangent):
            return (False)
        if (self.color != v.color):
            return (False)
        if (self.texcoord0 != v.texcoord0):
            return (False)
        if (self.texcoord1 != v.texcoord1):
            return (False)
        return (True)

    # TODO: Why are we rolling our own hash function above? Is it faster/better somehow? Profile it!
    #def Hash(self):
    #    h = hash(
    #        self.position[0],
    #        self.position[1],
    #        self.position[2],
    #        self.normal[0],
    #        self.normal[1],
    #        self.normal[2],
    #        self.tangent[0],
    #        self.tangent[1],
    #        self.tangent[2],
    #        self.color[0],
    #        self.color[1],
    #        self.color[2],
    #        self.texcoord0[0],
    #        self.texcoord0[1],
    #        self.texcoord1[0],
    #        self.texcoord1[1]
    #    )
    #    self.hash = h
    def Hash(self):
        h = hash(self.position[0])
        h = h * 21737 + hash(self.position[1])
        h = h * 21737 + hash(self.position[2])
        h = h * 21737 + hash(self.normal[0])
        h = h * 21737 + hash(self.normal[1])
        h = h * 21737 + hash(self.normal[2])
        h = h * 21737 + hash(self.tangent[0])
        h = h * 21737 + hash(self.tangent[1])
        h = h * 21737 + hash(self.tangent[2])
        h = h * 21737 + hash(self.color[0])
        h = h * 21737 + hash(self.color[1])
        h = h * 21737 + hash(self.color[2])
        h = h * 21737 + hash(self.texcoord0[0])
        h = h * 21737 + hash(self.texcoord0[1])
        h = h * 21737 + hash(self.texcoord1[0])
        h = h * 21737 + hash(self.texcoord1[1])
        self.hash = h


class OpenGexExporter(bpy.types.Operator, ExportHelper):
    """Export to OpenGEX format"""
    bl_idname = "export_scene.ogex"
    bl_label = "Export OpenGEX"
    filename_ext = ".ogex"

    option_export_selection: bpy.props.BoolProperty(name = "Export Selection Only", description = "Export only selected objects", default = False)
    option_sample_animation: bpy.props.BoolProperty(name = "Force Sampled Animation", description = "Always export animation as per-frame samples", default = False)

    def Write(self, text):
        self.file.write(text)

    def IndentWrite(self, text, extra = 0, newline = False):
        if (newline):
            self.file.write(B"\n")
        for i in range(self.indentLevel + extra):
            self.file.write(B"\t")
        self.file.write(text)

    def WriteString(self, s):
        self.file.write(bytes(f"\"{s}\"", "UTF-8"))

    def WriteInt(self, i):
        self.file.write(bytes(str(i), "UTF-8"))

    def WriteFloat(self, f):
        if ((math.isinf(f)) or (math.isnan(f))):
            self.file.write(B"0.0")
        elif (f == 0):
            self.file.write(B"0")
        else:
            as_int = struct.unpack('<I', struct.pack('<f', f))[0]
            #as_hex = hex(as_int)                 # As hex string "0x2f"
            as_pad = "{0:#010x}".format(as_int)   # As hex string padded with 0s "0x2f000000"
            #as_str = str(f)                      # As string "3.5"
            self.file.write(bytes(as_pad, "UTF-8"))

    #| matrices:    11  13 -12  14
    #|              31  33 -32  34
    #|             -21 -23  22 -24
    #|               0   0   0  1
    def WriteMatrix(self, matrix):
        self.Write(B"[")
        self.IndentWrite(B"", 1, True)
        self.WriteFloat(matrix[0][0])
        self.Write(B", ")
        self.WriteFloat(matrix[2][0])
        self.Write(B", ")
        self.WriteFloat(-matrix[1][0])
        self.Write(B", ")
        self.WriteFloat(matrix[3][0])
        self.Write(B", ")

        self.IndentWrite(B"", 1, True)
        self.WriteFloat(matrix[0][2])
        self.Write(B", ")
        self.WriteFloat(matrix[2][2])
        self.Write(B", ")
        self.WriteFloat(-matrix[1][2])
        self.Write(B", ")
        self.WriteFloat(matrix[3][1])
        self.Write(B", ")

        self.IndentWrite(B"", 1, True)
        self.WriteFloat(-matrix[0][1])
        self.Write(B", ")
        self.WriteFloat(-matrix[2][1])
        self.Write(B", ")
        self.WriteFloat(matrix[1][1])
        self.Write(B", ")
        self.WriteFloat(matrix[3][2])
        self.Write(B", ")

        self.IndentWrite(B"", 1, True)
        self.WriteFloat(matrix[0][3])
        self.Write(B", ")
        self.WriteFloat(matrix[2][3])
        self.Write(B", ")
        self.WriteFloat(-matrix[1][3])
        self.Write(B", ")
        self.WriteFloat(matrix[3][3])
        self.Write(B"\n")
        self.IndentWrite(B"]\n")

    # def WriteMatrix(self, matrix):
    #     self.Write(B"[")
    #     self.IndentWrite(B"", 1, True)
    #     self.WriteFloat(matrix[0][0])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[1][0])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[2][0])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[3][0])
    #     self.Write(B",")

    #     self.IndentWrite(B"", 1, True)
    #     self.WriteFloat(matrix[0][1])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[1][1])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[2][1])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[3][1])
    #     self.Write(B",")

    #     self.IndentWrite(B"", 1, True)
    #     self.WriteFloat(matrix[0][2])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[1][2])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[2][2])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[3][2])
    #     self.Write(B",")

    #     self.IndentWrite(B"", 1, True)
    #     self.WriteFloat(matrix[0][3])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[1][3])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[2][3])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[3][3])
    #     self.Write(B"\n")
    #     self.IndentWrite(B"]\n")

    #| matrices:    00  02 -01  03
    #|              20  22 -21  23
    #|             -10 -12  11 -13
    #|               0   0   0  1
    def WriteMatrixFlat(self, matrix):
        self.IndentWrite(B"[")
        self.WriteFloat(matrix[0][0])
        self.Write(B", ")
        self.WriteFloat(matrix[2][0])
        self.Write(B", ")
        self.WriteFloat(-matrix[1][0])
        self.Write(B", ")
        self.WriteFloat(matrix[3][0])
        self.Write(B", ")
        self.WriteFloat(matrix[0][2])
        self.Write(B", ")
        self.WriteFloat(matrix[2][2])
        self.Write(B", ")
        self.WriteFloat(-matrix[1][2])
        self.Write(B", ")
        self.WriteFloat(matrix[3][1])
        self.Write(B", ")
        self.WriteFloat(-matrix[0][1])
        self.Write(B", ")
        self.WriteFloat(-matrix[2][1])
        self.Write(B", ")
        self.WriteFloat(matrix[1][1])
        self.Write(B", ")
        self.WriteFloat(matrix[3][2])
        self.Write(B", ")
        self.WriteFloat(matrix[0][3])
        self.Write(B", ")
        self.WriteFloat(matrix[2][3])
        self.Write(B", ")
        self.WriteFloat(-matrix[1][3])
        self.Write(B", ")
        self.WriteFloat(matrix[3][3])
        self.Write(B"]")

    # def WriteMatrixFlat(self, matrix):
    #     self.IndentWrite(B"[")
    #     self.WriteFloat(matrix[0][0])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[1][0])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[2][0])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[3][0])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[0][1])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[1][1])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[2][1])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[3][1])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[0][2])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[1][2])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[2][2])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[3][2])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[0][3])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[1][3])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[2][3])
    #     self.Write(B", ")
    #     self.WriteFloat(matrix[3][3])
    #     self.Write(B"]")

    def WriteColor(self, color):
        self.Write(B"[")
        self.WriteFloat(color[0])
        self.Write(B", ")
        self.WriteFloat(color[1])
        self.Write(B", ")
        self.WriteFloat(color[2])
        self.Write(B"]")

    def WriteFileName(self, filename):
        length = len(filename)
        if (length != 0):
            self.Write(B"\"")
            if ((length > 2) and (filename[1] == ":")):
                self.Write(B"//")
                self.Write(bytes(filename[0], "UTF-8"))
                self.Write(bytes(filename[2:length].replace("\\", "/"), "UTF-8"))
            else:
                self.Write(bytes(filename.replace("\\", "/"), "UTF-8"))
            self.Write(B"\"")

    def WriteIntArray(self, valueArray):
        count = len(valueArray)

        self.IndentWrite(B"")
        for i in range(count):
            self.WriteInt(valueArray[i])
            if i == count - 1:
                self.Write(B"\n")
                break
            self.Write(B", ")
            if not (i + 1) % kOutputColumns:
                self.Write(B"\n")
                self.IndentWrite(B"")

    def WriteFloatArray(self, valueArray):
        count = len(valueArray)

        self.IndentWrite(B"")
        for i in range(count):
            self.WriteFloat(valueArray[i])
            if i == count - 1:
                self.Write(B"\n")
                break
            self.Write(B", ")
            if not (i + 1) % kOutputColumns:
                self.Write(B"\n")
                self.IndentWrite(B"")

    # x, y
    def WriteVector2D(self, vector):
        self.Write(B"[")
        self.WriteFloat(vector[0])
        self.Write(B", ")
        self.WriteFloat(vector[1])
        self.Write(B"]")

    #| vectors:     x z -y
    # x, y, z
    def WriteVector3D(self, vector):
        self.Write(B"[")
        self.WriteFloat(vector[0])
        self.Write(B", ")
        self.WriteFloat(vector[2])
        self.Write(B", ")
        self.WriteFloat(-vector[1])
        self.Write(B"]")

    # def WriteVector3D(self, vector):
    #     self.Write(B"[")
    #     self.WriteFloat(vector[0])
    #     self.Write(B", ")
    #     self.WriteFloat(vector[1])
    #     self.Write(B", ")
    #     self.WriteFloat(vector[2])
    #     self.Write(B"]")

    #| vectors:     x z -y
    # angle, x, y, z
    def WriteAxisAngle(self, vector):
        self.Write(B"[")
        self.WriteFloat(vector[0])
        self.Write(B", ")
        self.WriteFloat(vector[1])
        self.Write(B", ")
        self.WriteFloat(vector[3])
        self.Write(B", ")
        self.WriteFloat(-vector[2])
        self.Write(B"]")

    # def WriteAxisAngle(self, vector):
    #     self.Write(B"[")
    #     self.WriteFloat(vector[0])
    #     self.Write(B", ")
    #     self.WriteFloat(vector[1])
    #     self.Write(B", ")
    #     self.WriteFloat(vector[2])
    #     self.Write(B", ")
    #     self.WriteFloat(vector[3])
    #     self.Write(B"]")

    #| quaternions: x z -y, w
    # x, y, z, w
    def WriteQuaternion(self, quaternion):
        self.Write(B"[")
        self.WriteFloat(quaternion[1])
        self.Write(B", ")
        self.WriteFloat(quaternion[3])
        self.Write(B", ")
        self.WriteFloat(-quaternion[2])
        self.Write(B", ")
        self.WriteFloat(quaternion[0])
        self.Write(B"]")

    # def WriteQuaternion(self, quaternion):
    #     self.Write(B"[")
    #     self.WriteFloat(quaternion[1])
    #     self.Write(B", ")
    #     self.WriteFloat(quaternion[2])
    #     self.Write(B", ")
    #     self.WriteFloat(quaternion[3])
    #     self.Write(B", ")
    #     self.WriteFloat(quaternion[0])
    #     self.Write(B"]")

    def WriteVertexArray2D(self, vertexArray, attrib):
        count = len(vertexArray)

        self.IndentWrite(B"")
        for i in range(count):
            self.WriteVector2D(getattr(vertexArray[i], attrib))
            if i == count - 1:
                self.Write(B"\n")
                break
            self.Write(B", ")
            if not (i + 1) % kOutputColumns:
                self.Write(B"\n")
                self.IndentWrite(B"")

    def WriteVertexArray3D(self, vertexArray, attrib):
        count = len(vertexArray)

        self.IndentWrite(B"")
        for i in range(count):
            self.WriteVector3D(getattr(vertexArray[i], attrib))
            if i == count - 1:
                self.Write(B"\n")
                break
            self.Write(B", ")
            if not (i + 1) % kOutputColumns:
                self.Write(B"\n")
                self.IndentWrite(B"")

    def WriteMorphPositionArray3D(self, vertexArray, meshVertexArray):
        count = len(vertexArray)

        self.IndentWrite(B"")
        for i in range(count):
            self.WriteVector3D(meshVertexArray[vertexArray[i].vertexIndex].co)
            if i == count - 1:
                self.Write(B"\n")
                break
            self.Write(B", ")
            if not (i + 1) % kOutputColumns:
                self.Write(B"\n")
                self.IndentWrite(B"")

    def WriteMorphNormalArray3D(self, vertexArray, meshVertexArray, tessFaceArray):
        count = len(vertexArray)

        self.IndentWrite(B"")
        for i in range(count):
            face = tessFaceArray[vertexArray[i].faceIndex]
            self.WriteVector3D(meshVertexArray[vertexArray[i].vertexIndex].normal if (face.use_smooth) else face.normal)
            if i == count - 1:
                self.Write(B"\n")
                break
            self.Write(B", ")
            if not (i + 1) % kOutputColumns:
                self.Write(B"\n")
                self.IndentWrite(B"")

    def WriteTriangle(self, triangleIndex, indexTable):
        i = triangleIndex * 3
        self.WriteInt(indexTable[i])
        self.Write(B", ")
        self.WriteInt(indexTable[i + 1])
        self.Write(B", ")
        self.WriteInt(indexTable[i + 2])

    def WriteTriangleArray(self, count, indexTable):
        self.IndentWrite(B"")
        for i in range(count):
            self.WriteTriangle(i, indexTable)
            if i == count - 1:
                self.Write(B"\n")
                break
            self.Write(B", ")
            if not (i + 1) % kOutputColumns:
                self.Write(B"\n")
                self.IndentWrite(B"")

    def WriteNodeTable(self, objectRef):
        first = True
        for node in objectRef[1]["nodeTable"]:
            if (first):
                self.Write(B"  # Node Table: ")
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

        for face in mesh.polygons:
            assert(len(face.vertices) == 3)

            # Need to get tangents from loops, but position/normals from vertices??
            l1 = mesh.loops[face.loop_indices[0]]
            l2 = mesh.loops[face.loop_indices[1]]
            l3 = mesh.loops[face.loop_indices[2]]

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
            exportVertex.tangent = l1.tangent
            exportVertexArray.append(exportVertex)

            exportVertex = ExportVertex()
            exportVertex.vertexIndex = k2
            exportVertex.faceIndex = faceIndex
            exportVertex.position = v2.co
            exportVertex.normal = v2.normal if (face.use_smooth) else face.normal
            exportVertex.tangent = l2.tangent
            exportVertexArray.append(exportVertex)

            exportVertex = ExportVertex()
            exportVertex.vertexIndex = k3
            exportVertex.faceIndex = faceIndex
            exportVertex.position = v3.co
            exportVertex.normal = v3.normal if (face.use_smooth) else face.normal
            exportVertex.tangent = l3.tangent
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
            for tri in mesh.loop_triangles:
                assert(len(tri.loops) == 3)
                for loop_index in tri.loops:
                    exportVertexArray[vertexIndex].texcoord0 = mesh.uv_layers[0].data[loop_index].uv
                    if (texcoordCount > 1):
                        exportVertexArray[vertexIndex].texcoord1 = mesh.uv_layers[1].data[loop_index].uv
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

    # @staticmethod
    # def CollectBoneAnimation(armature, name):
    #     path = "pose.bones[\"" + name + "\"]."
    #     curveArray = []

    #     if (armature.animation_data):
    #         action = armature.animation_data.action
    #         if (action):
    #             for fcurve in action.fcurves:
    #                 if (fcurve.data_path.startswith(path)):
    #                     curveArray.append(fcurve)

    #     return (curveArray)

    @staticmethod
    def HasBoneAnimation(armature, name):
        path = "pose.bones[\"" + name + "\"]."
        curveArray = []

        if (armature.animation_data):
            action = armature.animation_data.action
            if (action):
                for fcurve in action.fcurves:
                    if (fcurve.data_path.startswith(path)):
                        return True
            nla_tracks = armature.animation_data.nla_tracks
            for track in nla_tracks:
                for strip in track.strips:
                    action = strip.action
                    if (action):
                        for fcurve in action.fcurves:
                            if (fcurve.data_path.startswith(path)):
                                return True

        return False

    def ExportKeyTimes(self, fcurve):
        self.IndentWrite(B"key: {\n")
        self.indentLevel += 1
        self.IndentWrite(B"kind: \"value\"\n")
        self.IndentWrite(B"type: \"float\"\n")
        self.IndentWrite(B"data: [\n")
        self.indentLevel += 1

        keyCount = len(fcurve.keyframe_points)
        for i in range(keyCount):
            if (i > 0):
                self.Write(B", ")

            time = fcurve.keyframe_points[i].co[0] - self.beginFrame
            self.WriteFloat(time * self.frameTime)

        self.indentLevel -= 1
        self.IndentWrite(B"]\n")
        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

    def ExportKeyTimeControlPoints(self, fcurve):
        self.IndentWrite(B"key: {\n")
        self.indentLevel += 1
        self.IndentWrite(B"kind: \"-control\"\n")
        self.IndentWrite(B"type: \"float\"\n")
        self.IndentWrite(B"data: [\n")
        self.indentLevel += 1

        keyCount = len(fcurve.keyframe_points)
        for i in range(keyCount):
            if (i > 0):
                self.Write(B", ")

            ctrl = fcurve.keyframe_points[i].handle_left[0] - self.beginFrame
            self.WriteFloat(ctrl * self.frameTime)

        self.indentLevel -= 1
        self.IndentWrite(B"]\n")
        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

        self.IndentWrite(B"key: {\n")
        self.indentLevel += 1
        self.IndentWrite(B"kind: \"+control\"\n")
        self.IndentWrite(B"type: \"float\"\n")
        self.IndentWrite(B"data: [\n")
        self.indentLevel += 1

        for i in range(keyCount):
            if (i > 0):
                self.Write(B", ")

            ctrl = fcurve.keyframe_points[i].handle_right[0] - self.beginFrame
            self.WriteFloat(ctrl * self.frameTime)

        self.indentLevel -= 1
        self.IndentWrite(B"]\n")
        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

    def ExportKeyValues(self, fcurve):
        self.IndentWrite(B"key: {\n")
        self.indentLevel += 1
        self.IndentWrite(B"kind: \"value\"\n")
        self.IndentWrite(B"type: \"float\"\n")
        self.IndentWrite(B"data: [\n")
        self.indentLevel += 1

        keyCount = len(fcurve.keyframe_points)
        for i in range(keyCount):
            if (i > 0):
                self.Write(B", ")

            value = fcurve.keyframe_points[i].co[1]
            self.WriteFloat(value)

        self.indentLevel -= 1
        self.IndentWrite(B"]\n")
        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

    def ExportKeyValueControlPoints(self, fcurve):
        self.IndentWrite(B"key: {\n")
        self.indentLevel += 1
        self.IndentWrite(B"kind: \"-control\"\n")
        self.IndentWrite(B"type: \"float\"\n")
        self.IndentWrite(B"data: [\n")
        self.indentLevel += 1

        keyCount = len(fcurve.keyframe_points)
        for i in range(keyCount):
            if (i > 0):
                self.Write(B", ")

            ctrl = fcurve.keyframe_points[i].handle_left[1]
            self.WriteFloat(ctrl)

        self.indentLevel -= 1
        self.IndentWrite(B"]\n")
        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

        self.IndentWrite(B"key: {\n")
        self.indentLevel += 1
        self.IndentWrite(B"kind: \"+control\"\n")
        self.IndentWrite(B"type: \"float\"\n")
        self.IndentWrite(B"data: [\n")
        self.indentLevel += 1

        for i in range(keyCount):
            if (i > 0):
                self.Write(B", ")

            ctrl = fcurve.keyframe_points[i].handle_right[1]
            self.WriteFloat(ctrl)

        self.indentLevel -= 1
        self.IndentWrite(B"]\n")
        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

    def ExportAnimationTrack(self, fcurve, kind, target, target_index, newline):

        # This function exports a single animation track. The curve types for the
        # Time and Value structures are given by the kind parameter.

        self.IndentWrite(B"track: {\n")
        self.indentLevel += 1

        self.IndentWrite(B"target: ")
        self.WriteInt(target)
        self.Write(B"\n")

        self.IndentWrite(B"target_index: ")
        self.WriteInt(target_index)
        self.Write(B"\n")

        if (kind != kAnimationBezier):
            self.IndentWrite(B"time: {\n")
            self.indentLevel += 1
            self.IndentWrite(B"curve: \"linear\"\n")
            self.ExportKeyTimes(fcurve)
            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

            self.IndentWrite(B"value: {\n")
            self.indentLevel += 1
            self.IndentWrite(B"curve: \"linear\"\n")
            self.ExportKeyValues(fcurve)
            self.indentLevel -= 1
            self.IndentWrite(B"}\n")
        else:
            self.IndentWrite(B"time: {\n")
            self.indentLevel += 1
            self.IndentWrite(B"curve: \"bezier\"\n")
            self.ExportKeyTimes(fcurve)
            self.ExportKeyTimeControlPoints(fcurve)
            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

            self.IndentWrite(B"value: {\n")
            self.indentLevel += 1
            self.IndentWrite(B"curve: \"bezier\"\n")
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
            self.IndentWrite(B"animation: {  # ExportNodeSampledAnimation\n")
            self.indentLevel += 1

            self.IndentWrite(B"track: {\n")
            self.indentLevel += 1

            self.IndentWrite(B"time: {\n")
            self.indentLevel += 1
            self.IndentWrite(B"curve: \"linear\"\n")
            self.IndentWrite(B"key: {\n")
            self.indentLevel += 1
            self.IndentWrite(B"kind: \"value\"\n")
            self.IndentWrite(B"type: \"float\"\n")
            self.IndentWrite(B"data: [\n")
            self.indentLevel += 1

            self.IndentWrite(B"")
            for i in range(self.beginFrame, self.endFrame + 1):
                self.WriteFloat((i - self.beginFrame) * self.frameTime)
                if i == self.endFrame:
                    self.Write(B"\n")
                    break
                self.Write(B", ")
                if not (i - self.beginFrame) % kOutputColumns:
                    self.Write(B"\n")
                    self.IndentWrite(B"")

            self.indentLevel -= 1
            self.IndentWrite(B"]\n")
            self.indentLevel -= 1
            self.IndentWrite(B"}\n")
            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

            self.indentLevel -= 1
            self.IndentWrite(B"value: {\n")
            self.indentLevel += 1
            self.IndentWrite(B"curve: \"linear\"\n")
            self.IndentWrite(B"key: {\n")
            self.indentLevel += 1
            self.IndentWrite(B"kind: \"value\"\n")
            self.IndentWrite(B"type: \"mat4\"\n")
            self.IndentWrite(B"data: [\n")
            self.indentLevel += 1

            for i in range(self.beginFrame, self.endFrame):
                scene.frame_set(i)
                self.WriteMatrixFlat(node.matrix_local)
                self.Write(B",\n")

            scene.frame_set(self.endFrame)
            self.WriteMatrixFlat(node.matrix_local)

            self.indentLevel -= 1
            self.IndentWrite(B"]\n")
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
            self.IndentWrite(B"animation: {  # BoneSampledAnimation\n")
            self.indentLevel += 1

            self.IndentWrite(B"track: {\n")
            self.indentLevel += 1

            self.IndentWrite(B"target: \"transform\"\n")

            self.IndentWrite(B"time: {\n")
            self.indentLevel += 1
            self.IndentWrite(B"curve: \"linear\"\n")
            self.IndentWrite(B"key: {\n")
            self.indentLevel += 1
            self.IndentWrite(B"kind: \"value\"\n")
            self.IndentWrite(B"type: \"float\"\n")
            self.IndentWrite(B"data: [\n")
            self.indentLevel += 1

            self.IndentWrite(B"")
            for i in range(self.beginFrame, self.endFrame + 1):
                self.WriteFloat((i - self.beginFrame) * self.frameTime)
                if i == self.endFrame:
                    self.Write(B"\n")
                    break
                self.Write(B", ")
                idx = i - self.beginFrame
                if idx and not (idx + 1) % kOutputColumns:
                    self.Write(B"\n")
                    self.IndentWrite(B"")

            self.indentLevel -= 1
            self.IndentWrite(B"]\n")
            self.indentLevel -= 1
            self.IndentWrite(B"}\n")
            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

            self.IndentWrite(B"value: {\n")
            self.indentLevel += 1
            self.IndentWrite(B"curve: \"linear\"\n")
            self.IndentWrite(B"key: {\n")
            self.indentLevel += 1
            self.IndentWrite(B"kind: \"value\"\n")
            self.IndentWrite(B"type: \"mat4\"\n")
            self.IndentWrite(B"data: [\n")
            self.indentLevel += 1

            parent = poseBone.parent
            if (parent):
                for i in range(self.beginFrame, self.endFrame + 1):
                    scene.frame_set(i)
                    if (math.fabs(parent.matrix.determinant()) > kExportEpsilon):
                        self.WriteMatrixFlat(parent.matrix.inverted() @ poseBone.matrix)
                    else:
                        self.WriteMatrixFlat(poseBone.matrix)

                    if i == self.endFrame:
                        self.Write(B"\n")
                        break

                    self.Write(B",\n")

            else:
                for i in range(self.beginFrame, self.endFrame):
                    scene.frame_set(i)
                    self.WriteMatrixFlat(poseBone.matrix)
                    self.Write(B",\n")

                scene.frame_set(self.endFrame)
                self.WriteMatrixFlat(poseBone.matrix)
                self.Write(B"\n")

            self.indentLevel -= 1
            self.IndentWrite(B"]\n")
            self.indentLevel -= 1
            self.IndentWrite(B"}\n")
            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

        scene.frame_set(currentFrame, subframe=currentSubframe)

    def ExportMorphWeightSampledAnimationTrack(self, block, target, target_index, scene, newline):
        currentFrame = scene.frame_current
        currentSubframe = scene.frame_subframe

        self.IndentWrite(B"track: {\n")
        self.indentLevel += 1

        self.IndentWrite(B"target: ")
        self.WriteString(target)
        self.Write(B"\n")

        self.IndentWrite(B"target_index: ")
        self.WriteInt(target_index)
        self.Write(B"\n")

        self.IndentWrite(B"time: {\n")
        self.indentLevel += 1
        self.IndentWrite(B"curve: \"linear\"\n")
        self.IndentWrite(B"key: {\n")
        self.indentLevel += 1
        self.IndentWrite(B"kind: \"value\"\n")
        self.IndentWrite(B"type: \"float\"\n")
        self.IndentWrite(B"data: [\n")
        self.indentLevel += 1

        self.IndentWrite(B"")
        for i in range(self.beginFrame, self.endFrame + 1):
            self.WriteFloat((i - self.beginFrame) * self.frameTime)
            if i == self.endFrame:
                self.Write(B"\n")
                break
            self.Write(B", ")
            idx = i - self.beginFrame
            if idx and not (idx + 1) % kOutputColumns:
                self.Write(B"\n")
                self.IndentWrite(B"")

        self.indentLevel -= 1
        self.IndentWrite(B"]\n")
        self.indentLevel -= 1
        self.IndentWrite(B"}\n")
        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

        self.IndentWrite(B"value: {\n")
        self.indentLevel += 1
        self.IndentWrite(B"curve: \"linear\"\n")
        self.IndentWrite(B"key: {\n")
        self.indentLevel += 1
        self.IndentWrite(B"kind: \"value\"\n")
        self.IndentWrite(B"type: \"float\"\n")
        self.IndentWrite(B"data: [\n")
        self.indentLevel += 1

        self.IndentWrite(B"")
        for i in range(self.beginFrame, self.endFrame + 1):
            scene.frame_set(i)
            self.WriteFloat(block.value)
            if i == self.endFrame:
                self.Write(B"\n")
                break
            self.Write(B", ")
            idx = i - self.beginFrame
            if idx and not (idx + 1) % kOutputColumns:
                self.Write(B"\n")
                self.IndentWrite(B"")

        self.indentLevel -= 1
        self.IndentWrite(B"]\n")
        self.indentLevel -= 1
        self.IndentWrite(B"}\n")
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

            self.IndentWrite(B"transform: {  # ExportNodeTransform\n")
            self.indentLevel += 1

            self.IndentWrite(B"position: ")
            self.WriteVector3D(node.location)
            self.Write(B"\n")
            self.IndentWrite(B"orientation: ")
            self.WriteQuaternion(node.rotation_quaternion)
            #self.WriteQuaternion(node.matrix_local.to_quaternion())
            self.Write(B"\n")

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
                        self.WriteAxisAngle(node.rotation_axis_angle)
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

            self.IndentWrite(B"animation: {  # ExportNodeTransform\n")
            self.indentLevel += 1
            self.IndentWrite(B"begin: ")
            self.WriteFloat((action.frame_range[0] - self.beginFrame) * self.frameTime)
            self.Write(B"\n")
            self.IndentWrite(B"end: ")
            self.WriteFloat((action.frame_range[1] - self.beginFrame) * self.frameTime)
            self.Write(B"\n")

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
        #curveArray = self.CollectBoneAnimation(armature, bone.name)
        #animation = ((len(curveArray) != 0) or (self.sampleAnimationFlag))
        hasCurves = self.HasBoneAnimation(armature, bone.name)
        animation = (hasCurves or (self.sampleAnimationFlag))

        poseBone = armature.pose.bones.get(bone.name)
        if (poseBone):
            transform = poseBone.matrix.copy()
            parentPoseBone = poseBone.parent
            if ((parentPoseBone) and (math.fabs(parentPoseBone.matrix.determinant()) > kExportEpsilon)):
                transform = parentPoseBone.matrix.inverted() @ transform
        else:
            transform = bone.matrix_local.copy()
            parentBone = bone.parent
            if ((parentBone) and (math.fabs(parentBone.matrix_local.determinant()) > kExportEpsilon)):
                transform = parentBone.matrix_local.inverted() @ transform

        self.IndentWrite(B"transform: {  # ExportBoneTransform\n")
        self.indentLevel += 1

        self.IndentWrite(B"position: ")
        self.WriteVector3D(transform.translation)
        self.Write(B"\n")
        self.IndentWrite(B"orientation: ")
        self.WriteQuaternion(transform.to_quaternion())
        self.Write(B"\n")

        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

        if ((animation) and (poseBone)):
            self.ExportBoneSampledAnimation(poseBone, scene)

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

        self.IndentWrite(B"morph_weights: [\n")
        self.indentLevel += 1

        for k in range(len(shapeKeys.key_blocks)):
            block = shapeKeys.key_blocks[k]
            self.IndentWrite(B"")
            self.WriteFloat(block.value if (block.name != referenceName) else 1.0)
            if k < len(shapeKeys.key_blocks) - 1:
                self.Write(B", ")
            self.Write(B"\n")

        self.indentLevel -= 1
        self.IndentWrite(B"]\n")

        if (animated):
            self.IndentWrite(B"animation: {  # ExportMorphWeights\n")
            self.indentLevel += 1
            self.IndentWrite(B"begin: ")
            self.WriteFloat((action.frame_range[0] - self.beginFrame) * self.frameTime)
            self.Write(B"\n")
            self.IndentWrite(B"end: ")
            self.WriteFloat((action.frame_range[1] - self.beginFrame) * self.frameTime)
            self.Write(B"\n")

            structFlag = False

            for a in range(len(curveArray)):
                k = indexArray[a]
                target = "morph_weight"

                fcurve = curveArray[a]
                kind = OpenGexExporter.ClassifyAnimationCurve(fcurve)
                if ((kind != kAnimationSampled) and (not self.sampleAnimationFlag)):
                    self.ExportAnimationTrack(fcurve, kind, target, k, structFlag)
                else:
                    self.ExportMorphWeightSampledAnimationTrack(shapeKeys.key_blocks[k], target, k, scene, structFlag)

                structFlag = True

            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

    def ExportBone(self, armature, bone, scene):
        nodeRef = self.nodeArray.get(bone)
        if (nodeRef):
            self.IndentWrite(structIdentifier[nodeRef["nodeType"]])
            self.Write(B": {\n")
            self.indentLevel += 1

            name = bone.name or nodeRef["structName"]
            if (name != ""):
                self.IndentWrite(B"name: ")
                self.WriteString(name)
                self.Write(B"\n")

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
            self.IndentWrite(structIdentifier[type])
            self.Write(B": {\n")
            self.indentLevel += 1

            if (type == kNodeTypeGeometry):
                if (node.hide_render):
                    self.IndentWrite(B"visible: false\n")

            # Export the node's name if it has one.

            name = node.name or nodeRef["structName"]
            if (name != ""):
                self.IndentWrite(B"name: ")
                self.WriteString(name)
                self.Write(B"\n")

            # Export the object reference and material references.

            object = node.data

            if (type == kNodeTypeGeometry):
                if (not object in self.geometryArray):
                    self.geometryArray[object] = {"structName" : bytes("geometry" + str(len(self.geometryArray) + 1), "UTF-8"), "nodeTable" : [node]}
                else:
                    self.geometryArray[object]["nodeTable"].append(node)

                self.IndentWrite(B"mesh: ")
                self.WriteString(object.name)
                self.Write(B"\n")

                self.IndentWrite(B"materials: [\n")
                self.indentLevel += 1

                for i in range(len(node.material_slots)):
                    material = node.material_slots[i].material
                    self.materialArray[material] = {"structName" : bytes("material" + str(len(self.materialArray) + 1), "UTF-8")}

                    self.IndentWrite(B"")
                    self.WriteString(node.material_slots[i].material.name)
                    if i < len(node.material_slots) - 1:
                        self.Write(B",")
                    self.Write(B"\n")

                self.indentLevel -= 1
                self.IndentWrite(B"]\n")

                shapeKeys = OpenGexExporter.GetShapeKeys(object)
                if (shapeKeys):
                    self.ExportMorphWeights(node, shapeKeys, scene)

            elif (type == kNodeTypeLight):
                if (not object in self.lightArray):
                    self.lightArray[object] = {"structName" : bytes("light" + str(len(self.lightArray) + 1), "UTF-8"), "nodeTable" : [node]}
                else:
                    self.lightArray[object]["nodeTable"].append(node)

                self.IndentWrite(B"light: ")
                self.WriteString(object.name)
                self.Write(B"\n")

            elif (type == kNodeTypeCamera):
                if (not object in self.cameraArray):
                    self.cameraArray[object] = {"structName" : bytes("camera" + str(len(self.cameraArray) + 1), "UTF-8"), "nodeTable" : [node]}
                else:
                    self.cameraArray[object]["nodeTable"].append(node)

                self.IndentWrite(B"camera: ")
                self.WriteString(object.name)
                self.Write(B"\n")

            if (poseBone):

                # If the node is parented to a bone and is not relative, then undo the bone's transform.

                if (math.fabs(poseBone.matrix.determinant()) > kExportEpsilon):
                    self.IndentWrite(B"transform: {  # poseBone.matrix.inverted() (ExportNode)\n")
                    self.indentLevel += 1

                    transform = poseBone.matrix.inverted()
                    self.IndentWrite(B"position: ")
                    self.WriteVector3D(transform.translation)
                    self.Write(B"\n")
                    self.IndentWrite(B"orientation: ")
                    self.WriteQuaternion(transform.to_quaternion())
                    self.Write(B"\n")

                    self.indentLevel -= 1
                    self.IndentWrite(B"}\n")

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

        self.IndentWrite(B"skin: {\n")
        self.indentLevel += 1

        # Write the skin bind pose transform.

        self.IndentWrite(B"transform: {  # node.matrix_world (ExportSkin)\n")
        self.indentLevel += 1

        self.IndentWrite(B"position: ")
        self.WriteVector3D(node.matrix_world.translation)
        self.Write(B"\n")
        self.IndentWrite(B"orientation: ")
        self.WriteQuaternion(node.matrix_world.to_quaternion())
        self.Write(B"\n")

        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

        # Export the skeleton, which includes an array of bone node references
        # and and array of per-bone bind pose transforms.

        self.IndentWrite(B"skeleton: {\n")
        self.indentLevel += 1

        # Write the bone node reference array.

        boneArray = armature.data.bones
        boneCount = len(boneArray)

        self.IndentWrite(B"bones: [  # string[")
        self.WriteInt(boneCount)
        self.Write(B"]\n")
        self.indentLevel += 1

        for i in range(boneCount):
            boneRef = self.FindNode(boneArray[i].name)
            if (boneRef):
                self.IndentWrite(B"")
                self.WriteString(boneArray[i].name)
            else:
                self.IndentWrite(B"")
                self.Write(B"null")

            if (i < boneCount - 1):
                self.Write(B",\n")
            else:
                self.Write(B"\n")

        self.indentLevel -= 1
        self.IndentWrite(B"]\n")

        # Write the bind pose location array.

        self.IndentWrite(B"bind_pose_positions: [  # vec3[")
        self.WriteInt(boneCount)
        self.Write(B"]\n")
        self.indentLevel += 1

        for i in range(boneCount):
            self.IndentWrite(B"")
            #self.WriteMatrixFlat(armature.matrix_world @ boneArray[i].matrix_local)
            self.WriteVector3D(armature.location + boneArray[i].head_local)
            if (i < boneCount - 1):
                self.Write(B",\n")
            else:
                self.Write(B"\n")

        self.indentLevel -= 1
        self.IndentWrite(B"]\n")

        # Write the bone pose rotation array.

        self.IndentWrite(B"bind_pose_orientations: [  # quat[")
        self.WriteInt(boneCount)
        self.Write(B"]\n")
        self.indentLevel += 1

        for i in range(boneCount):
            self.IndentWrite(B"")
            #self.WriteMatrixFlat(armature.matrix_world @ boneArray[i].matrix_local)
            self.WriteQuaternion(armature.rotation_quaternion @ boneArray[i].matrix_local.to_quaternion())
            if (i < boneCount - 1):
                self.Write(B",\n")
            else:
                self.Write(B"\n")

        self.indentLevel -= 1
        self.IndentWrite(B"]\n")

        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

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

        self.IndentWrite(B"bone_count_array: [  # u16[")
        self.WriteInt(len(boneCountArray))
        self.Write(B"]\n")
        self.indentLevel += 1
        self.WriteIntArray(boneCountArray)
        self.indentLevel -= 1
        self.IndentWrite(B"]\n")

        # Write the bone index array. The number of entries is the sum of the bone counts for all vertices.

        self.IndentWrite(B"bone_index_array: [  # u16[")
        self.WriteInt(len(boneIndexArray))
        self.Write(B"]\n")
        self.indentLevel += 1
        self.WriteIntArray(boneIndexArray)
        self.indentLevel -= 1
        self.IndentWrite(B"]\n")

        # Write the bone weight array. The number of entries is the sum of the bone counts for all vertices.

        self.IndentWrite(B"bone_weight_array: [  # float[")
        self.WriteInt(len(boneWeightArray))
        self.Write(B"]\n")
        self.indentLevel += 1
        self.WriteFloatArray(boneWeightArray)
        self.indentLevel -= 1
        self.IndentWrite(B"]\n")

        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

    def ExportGeometry(self, objectRef, scene):
        # This function exports a single geometry object.

        self.Write(B"geometry: {")
        # NOTE(dlb): Node table is just a comment
        self.WriteNodeTable(objectRef)
        self.Write(B"\n")
        self.indentLevel += 1

        node = objectRef[1]["nodeTable"][0]
        mesh = objectRef[0]

        self.IndentWrite(B"name: ")
        self.WriteString(node.name)
        self.Write(B"\n")

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

            self.IndentWrite(B"morphs: [\n")
            self.indentLevel += 1

            morphCount = len(shapeKeys.key_blocks)

            for k in range(len(shapeKeys.key_blocks)):
                block = shapeKeys.key_blocks[k]
                currentMorphValue.append(block.value)
                block.value = 0.0

                if (block.name != ""):
                    self.IndentWrite(B"{\n")
                    self.indentLevel += 1

                    self.IndentWrite(B"name: ")
                    self.WriteString(block.name)
                    self.Write(B"\n")

                    if ((relative) and (morphCount != baseIndex)):
                        self.IndentWrite(B"base: ")
                        self.WriteInt(baseIndex)
                        self.Write(B"\n")

                    self.indentLevel -= 1
                    self.IndentWrite(B"}")
                    if k < len(shapeKeys.key_blocks) - 1:
                        self.Write(B", ")
                    self.Write(B"\n")

            self.indentLevel -= 1
            self.IndentWrite(B"]\n")

            shapeKeys.key_blocks[0].value = 1.0
            mesh.update()

        self.IndentWrite(B"mesh: {\n")
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
        exportMesh.calc_tangents()

        # Triangulate mesh and remap vertices to eliminate duplicates.

        materialTable = []
        exportVertexArray = OpenGexExporter.DeindexMesh(exportMesh, materialTable)
        triangleCount = len(materialTable)

        indexTable = []
        unifiedVertexArray = OpenGexExporter.UnifyVertices(exportVertexArray, indexTable)
        vertexCount = len(unifiedVertexArray)

        # Write the position array.

        self.IndentWrite(B"vertex_array: {  # vec3[")
        self.WriteInt(vertexCount)
        self.Write(B"]\n")
        self.indentLevel += 1
        self.IndentWrite(B"attrib: \"position\"\n")
        self.IndentWrite(B"data: [\n")
        self.indentLevel += 1
        self.WriteVertexArray3D(unifiedVertexArray, "position")
        self.indentLevel -= 1
        self.IndentWrite(B"]\n")
        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

        # Write the normal array.

        self.IndentWrite(B"vertex_array: {  # vec3[")
        self.WriteInt(vertexCount)
        self.Write(B"]\n")
        self.indentLevel += 1
        self.IndentWrite(B"attrib: \"normal\"\n")
        self.IndentWrite(B"data: [\n")
        self.indentLevel += 1
        self.WriteVertexArray3D(unifiedVertexArray, "normal")
        self.indentLevel -= 1
        self.IndentWrite(B"]\n")
        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

         # Write the tangent array.

        self.IndentWrite(B"vertex_array: {  # vec3[")
        self.WriteInt(vertexCount)
        self.Write(B"]\n")
        self.indentLevel += 1
        self.IndentWrite(B"attrib: \"tangent\"\n")
        self.IndentWrite(B"data: [\n")
        self.indentLevel += 1
        self.WriteVertexArray3D(unifiedVertexArray, "tangent")
        self.indentLevel -= 1
        self.IndentWrite(B"]\n")
        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

        # Write the color array if it exists.

        colorCount = len(exportMesh.vertex_colors)
        if (colorCount > 0):
            self.IndentWrite(B"vertex_array: {  # vec3[")
            self.WriteInt(vertexCount)
            self.Write(B"]\n")
            self.indentLevel += 1
            self.IndentWrite(B"attrib: \"color\"\n")
            self.IndentWrite(B"data: [\n")
            self.indentLevel += 1
            self.WriteVertexArray3D(unifiedVertexArray, "color")
            self.indentLevel -= 1
            self.IndentWrite(B"]\n")
            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

        # Write the texcoord arrays.

        texcoordCount = len(exportMesh.uv_layers)
        if (texcoordCount > 0):
            self.IndentWrite(B"vertex_array: {  # vec2[")
            self.WriteInt(vertexCount)
            self.Write(B"]\n")
            self.indentLevel += 1
            self.IndentWrite(B"attrib: \"texcoord0\"\n")
            self.IndentWrite(B"data: [\n")
            self.indentLevel += 1
            self.WriteVertexArray2D(unifiedVertexArray, "texcoord0")
            self.indentLevel -= 1
            self.IndentWrite(B"]\n")
            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

            if (texcoordCount > 1):
                self.IndentWrite(B"vertex_array: {  # vec2[")
                self.WriteInt(vertexCount)
                self.Write(B"]\n")
                self.indentLevel += 1
                self.IndentWrite(B"attrib: \"texcoord1\"\n")
                self.IndentWrite(B"data: [\n")
                self.indentLevel += 1
                self.WriteVertexArray2D(unifiedVertexArray, "texcoord1")
                self.indentLevel -= 1
                self.IndentWrite(B"]\n")
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

                self.IndentWrite(B"vertex_array: {  # vec3[")
                self.WriteInt(vertexCount)
                self.Write(B"]\n")
                self.indentLevel += 1
                self.IndentWrite(B"attrib: \"position\"\n")
                self.IndentWrite(B"morph: ")
                self.WriteInt(m)
                #self.WriteString(shapeKeys.key_blocks[m].name)
                self.Write(B"\n")
                self.IndentWrite(B"data: [\n")
                self.indentLevel += 1
                self.WriteMorphPositionArray3D(unifiedVertexArray, morphMesh.vertices)
                self.indentLevel -= 1
                self.IndentWrite(B"]\n")
                self.indentLevel -= 1
                self.IndentWrite(B"}\n")

                # Write the morph target normal array.

                self.IndentWrite(B"vertex_array: {  # vec3[")
                self.WriteInt(vertexCount)
                self.Write(B"]\n")
                self.indentLevel += 1
                self.IndentWrite(B"attrib: \"normal\"\n")
                self.IndentWrite(B"morph: ")
                self.WriteInt(m)
                #self.WriteString(shapeKeys.key_blocks[m].name)
                self.Write(B"\n")
                self.IndentWrite(B"data: [\n")
                self.indentLevel += 1
                self.WriteMorphNormalArray3D(unifiedVertexArray, morphMesh.vertices, morphMesh.loop_triangles)
                self.indentLevel -= 1
                self.IndentWrite(B"]\n")
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

                self.IndentWrite(B"index_array: {  # u32[")
                self.WriteInt(materialTriangleCount[m])
                self.Write(B"]\n")
                self.indentLevel += 1
                self.IndentWrite(B"material_slot: ")
                #self.WriteString(bpy.data.materials[m].name)
                self.WriteInt(m)
                self.Write(B"\n")
                self.IndentWrite(B"data: [\n")
                self.indentLevel += 1
                self.WriteTriangleArray(materialTriangleCount[m], materialIndexTable)
                self.indentLevel -= 1
                self.IndentWrite(B"]\n")
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
        self.IndentWrite(B"}\n")

    def ExportLight(self, objectRef):
        # This function exports a single light object.
        self.Write(B"light: {")

        object = objectRef[0]
        type = object.type

        self.WriteNodeTable(objectRef)

        self.Write(B"\n")
        self.indentLevel += 1

        self.IndentWrite(B"name: ")
        self.WriteString(object.name)
        #self.Write(objectRef[1]["structName"])
        self.Write(B"\n")

        self.IndentWrite(B"type: ")
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
        self.Write(B"\n")

        if (object.use_shadow):
            self.IndentWrite(B"shadow: true\n")
        else:
            self.IndentWrite(B"shadow: false\n")

        # Export the light's color, and include a separate intensity if necessary.

        self.IndentWrite(B"color: ")
        self.WriteColor(object.color)
        self.Write(B"\n")

        intensity = object.energy
        # NOTE(dlb): Default light intensity = 1.0
        if (intensity != 1.0):
            self.IndentWrite(B"intensity: ")
            self.WriteFloat(intensity)
            self.Write(B"\n")

        if (pointFlag):
            # Export a separate attenuation function for each type that's in use.
            falloff = object.falloff_type

            if (falloff == "INVERSE_LINEAR"):
                self.IndentWrite(B"atten: {\n")
                self.indentLevel += 1
                self.IndentWrite(B"kind: \"distance\"\n")
                self.IndentWrite(B"curve: \"inverse\"\n")
                self.IndentWrite(B"scale: ")
                self.WriteFloat(object.distance)
                self.Write(B"\n")
                self.indentLevel -= 1
                self.IndentWrite(B"}\n")

            elif (falloff == "INVERSE_SQUARE"):
                self.IndentWrite(B"atten: {\n")
                self.indentLevel += 1
                self.IndentWrite(B"kind: \"distance\"\n")
                self.IndentWrite(B"curve: \"inverse_square\"\n")
                self.IndentWrite(B"scale: ")
                self.WriteFloat(math.sqrt(object.distance))
                self.Write(B"\n")
                self.indentLevel -= 1
                self.IndentWrite(B"}\n")

            elif (falloff == "LINEAR_QUADRATIC_WEIGHTED"):
                if (object.linear_attenuation != 0.0):
                    self.IndentWrite(B"atten: {\n")
                    self.indentLevel += 1
                    self.IndentWrite(B"kind: \"distance\"\n")
                    self.IndentWrite(B"curve: \"inverse\"\n")
                    self.IndentWrite(B"scale: ")
                    self.WriteFloat(object.distance)
                    self.Write(B"\n")
                    self.IndentWrite(B"constant: ")
                    self.WriteFloat(1.0)
                    self.Write(B"\n")
                    self.IndentWrite(B"linear: ")
                    self.WriteFloat(object.linear_attenuation)
                    self.Write(B"\n")
                    self.indentLevel -= 1
                    self.IndentWrite(B"}\n")

                if (object.quadratic_attenuation != 0.0):
                    self.IndentWrite(B"atten: {\n")
                    self.indentLevel += 1
                    self.IndentWrite(B"kind: \"distance\"\n")
                    self.IndentWrite(B"curve: \"inverse_square\"\n")
                    self.IndentWrite(B"scale: ")
                    self.WriteFloat(object.distance)
                    self.Write(B"\n")
                    self.IndentWrite(B"constant: ")
                    self.WriteFloat(1.0)
                    self.Write(B"\n")
                    self.IndentWrite(B"quadratic: ")
                    self.WriteFloat(object.quadratic_attenuation)
                    self.Write(B"\n")
                    self.indentLevel -= 1
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

                self.IndentWrite(B"atten: {\n")
                self.indentLevel += 1
                self.IndentWrite(B"kind: \"angle\"\n")
                self.IndentWrite(B"curve: \"linear\"\n")
                self.indentLevel -= 1
                self.IndentWrite(B"}\n")

                endAngle = object.spot_size * 0.5
                beginAngle = endAngle * (1.0 - object.spot_blend)

                self.IndentWrite(B"begin: ")
                self.WriteFloat(beginAngle)
                self.Write(B"\n")
                self.IndentWrite(B"end: ")
                self.WriteFloat(endAngle)
                self.Write(B"\n")

        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

    def ExportCamera(self, objectRef):
        # This function exports a single camera object.
        self.Write(B"camera: {")
        self.WriteNodeTable(objectRef)

        self.Write(B"\n")
        self.indentLevel += 1

        object = objectRef[0]

        self.IndentWrite(B"name: ")
        self.WriteString(object.name)
        self.Write(B"\n")
        self.IndentWrite(B"fov: ")
        self.WriteFloat(object.angle_x)
        self.Write(B"\n")
        self.IndentWrite(B"near: ")
        self.WriteFloat(object.clip_start)
        self.Write(B"\n")
        self.IndentWrite(B"far: ")
        self.WriteFloat(object.clip_end)
        self.Write(B"\n")

        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

    def ExportObjects(self, scene):
        for objectRef in self.geometryArray.items():
            print(f"Exporting geometry {objectRef[0]}")
            self.ExportGeometry(objectRef, scene)
        for objectRef in self.lightArray.items():
            print(f"Exporting light {objectRef[0]}")
            self.ExportLight(objectRef)
        for objectRef in self.cameraArray.items():
            print(f"Exporting camera {objectRef[0]}")
            self.ExportCamera(objectRef)

    def ExportTexture(self, texture, attrib):
        ogex_base = os.path.basename(self.filepath)
        filename = texture.filename(ogex_base)
        directory = os.path.dirname(self.filepath)
        path = os.path.join(directory, filename)

        # Write texture data to external file
        with open(path, 'wb') as f:
            f.write(texture.data())

        # This function exports a single texture from a material.
        self.IndentWrite(B"texture: {\n")
        self.indentLevel += 1

        self.IndentWrite(B"name: ")
        self.WriteFileName(filename)
        self.Write(B"\n")

        self.IndentWrite(B"path: ")
        self.WriteFileName(filename)
        self.Write(B"\n")

        # TODO(dlb): Do these props still exist in 2.8? If not, check how glTF finds texture transforms
        # If the texture has a scale and/or offset, then export a coordinate transform.
        uscale = 1.0 #textureSlot.scale[0]
        vscale = 1.0 #textureSlot.scale[1]
        uoffset = 0.0 #textureSlot.offset[0]
        voffset = 0.0 #textureSlot.offset[1]

        if ((uscale != 1.0) or (vscale != 1.0) or (uoffset != 0.0) or (voffset != 0.0)):
            #matrix = [[uscale, 0.0, 0.0, 0.0], [0.0, vscale, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0], [uoffset, voffset, 0.0, 1.0]]
            self.IndentWrite(B"uscale: ")
            self.WriteFloat(uscale)
            self.Write(B"\n")
            self.IndentWrite(B"vscale: ")
            self.WriteFloat(vscale)
            self.Write(B"\n")
            self.IndentWrite(B"uoffset: ")
            self.WriteFloat(uoffset)
            self.Write(B"\n")
            self.IndentWrite(B"voffset: ")
            self.WriteFloat(voffset)
            self.Write(B"\n")

        self.indentLevel -= 1
        self.IndentWrite(B"}\n")

    def ExportMaterials(self):
        # This function exports all of the materials used in the scene.
        for materialRef in self.materialArray.items():
            material = materialRef[0]

            print(f"Material {material.name} nodes:")
            for n in material.node_tree.nodes:
                print(f"  {n}")

            # TODO: Do we want to support factor + texture? We would have to figure out how to extract that from the node tree
            # If albedo texture is connected, set factor to all ones
            #alpha_cutoff        = gather_alpha_cutoff(material)
            #alpha_mode          = gather_alpha_mode(material)
            alpha_factor        = gather_alpha_factor(material)
            print(f"alpha_factor: {alpha_factor}")
            alpha_texture       = gather_alpha_texture(material)
            print(f"alpha_texture: {alpha_texture}")
            albedo_factor       = gather_albedo_factor(material)
            print(f"albedo_factor: {albedo_factor}")
            albedo_texture      = gather_albedo_texture(material)
            print(f"albedo_texture: {albedo_texture}")
            emissive_factor     = gather_emissive_factor(material)
            print(f"emissive_factor: {emissive_factor}")
            emissive_texture    = gather_emissive_texture(material)
            print(f"emissive_texture: {emissive_texture}")
            metallic_factor     = gather_metallic_factor(material)
            print(f"metallic_factor: {metallic_factor}")
            metallic_texture    = gather_metallic_texture(material)
            print(f"metallic_texture: {metallic_texture}")
            normal_factor       = gather_normal_factor(material)
            print(f"normal_factor: {normal_factor}")
            normal_texture      = gather_normal_texture(material)
            print(f"normal_texture: {normal_texture}")
            roughness_factor    = gather_roughness_factor(material)
            print(f"roughness_factor: {roughness_factor}")
            roughness_texture   = gather_roughness_texture(material)
            print(f"roughness_texture: {roughness_texture}")

            # TODO(dlb): Export factors if textures don't exist? Or both? Mix? Something?
            # TODO(dlb): Pack channels during export?
            if (alpha_texture):
                self.ExportTexture(alpha_texture, B"alpha")
            if (albedo_texture):
                self.ExportTexture(albedo_texture, B"albedo")
            if (emissive_texture):
                self.ExportTexture(emissive_texture, B"emission")
            if (metallic_texture):
                self.ExportTexture(metallic_texture, B"metallic")
            if (normal_texture):
                self.ExportTexture(normal_texture, B"normal")
            if (roughness_texture):
                self.ExportTexture(roughness_texture, B"roughness")

            # TODO(dlb): Check that textures which are going to be channel-combined have the same resolution
            # def tex_resolution_match(sockets: typing.Tuple[bpy.types.NodeSocket]):
            #     resolution = get_tex_from_socket(sockets[0]).shader_node.image.size
            #     if any(any(a != b for a, b in zip(get_tex_from_socket(elem).shader_node.image.size, resolution)) for elem in sockets):
            #         def format_image(image_node):
            #             return f"{image_node.image.name} ({image_node.image.size[0]}x{image_node.image.size[1]})"

            #         images = [format_image(get_tex_from_socket(elem).shader_node) for elem in sockets]
            #         print_console("ERROR", f"Image sizes do not match. In order to be merged into one image file, "
            #                             "images need to be of the same size. Images: {images}")
            #         return False

            #     return True

            self.IndentWrite(B"material: {\n")
            self.indentLevel += 1

            # TODO(dlb): Get rid of refs and ensure name is never None
            self.IndentWrite(B"name: ")
            self.WriteString(material.name or materialRef[1]["structName"])
            self.Write(B"\n")

            ogex_base = os.path.basename(self.filepath)
            # TODO(dlb): Export factors if textures don't exist? Or both? Mix? Something?
            # TODO(dlb): Pack channels during export?
            if (alpha_factor):
                self.IndentWrite(B"alpha_factor: ")
                self.WriteFloat(alpha_factor)
                self.Write(B"\n")
            if (alpha_texture):
                self.IndentWrite(B"alpha_texture: ")
                self.WriteFileName(alpha_texture.filename(ogex_base))
                self.Write(B"\n")
            if (albedo_factor):
                self.IndentWrite(B"albedo_factor: ")
                self.WriteColor(albedo_factor)
                self.Write(B"\n")
            if (albedo_texture):
                self.IndentWrite(B"albedo_texture: ")
                self.WriteFileName(albedo_texture.filename(ogex_base))
                self.Write(B"\n")
            if (emissive_factor):
                self.IndentWrite(B"emissive_factor: ")
                self.WriteColor(emissive_factor)
                self.Write(B"\n")
            if (emissive_texture):
                self.IndentWrite(B"emissive_texture: ")
                self.WriteFileName(emissive_texture.filename(ogex_base))
                self.Write(B"\n")
            if (metallic_factor):
                self.IndentWrite(B"metallic_factor: ")
                self.WriteFloat(metallic_factor)
                self.Write(B"\n")
            if (metallic_texture):
                self.IndentWrite(B"metallic_texture: ")
                self.WriteFileName(metallic_texture.filename(ogex_base))
                self.Write(B"\n")
            if (normal_factor):
                self.IndentWrite(B"normal_factor: ")
                self.WriteVector3D(normal_factor)
                self.Write(B"\n")
            if (normal_texture):
                self.IndentWrite(B"normal_texture: ")
                self.WriteFileName(normal_texture.filename(ogex_base))
                self.Write(B"\n")
            if (roughness_factor):
                self.IndentWrite(B"roughness_factor: ")
                self.WriteFloat(roughness_factor)
                self.Write(B"\n")
            if (roughness_texture):
                self.IndentWrite(B"roughness_texture: ")
                self.WriteFileName(roughness_texture.filename(ogex_base))
                self.Write(B"\n")

            self.indentLevel -= 1
            self.IndentWrite(B"}\n")

    def ExportMetrics(self, scene):
        scale = scene.unit_settings.scale_length

        if (scene.unit_settings.system == "IMPERIAL"):
            scale *= 0.3048
            log.warning("WARN: No automatic conversion from IMPERIAL units to METRIC units.")

        if (scale != 1.0):
            msg = f"ERROR: Talaria does not support scaled units (scale = {scale})."
            log.error(msg)
            assert(not "ERR_SCALED_UNITS")

        #self.Write(B"Metric (key = \"distance\") {float {")
        #self.WriteFloat(scale)
        #self.Write(B"}}\n")

        #self.Write(B"Metric (key = \"angle\") {float {")
        #self.WriteFloat(1.0)
        #self.Write(B"}}\n")
        #self.Write(B"Metric (key = \"time\") {float {")
        #self.WriteFloat(1.0)
        #self.Write(B"}}\n")

        #| TODO(dlb): Convert all coordinate bases from Blender (+Z up / +Y fwd)
        #| to Talaria (+Y up / -Z forward).
        #|---------------------------------------------------------------------
        #| vectors:     x z -y
        #| quaternions: x z -y, w
        #| matrices:    11  13 -12  14
        #|              31  33 -32  34
        #|             -21 -23  22 -24
        #|               0   0   0  1
        #|---------------------------------------------------------------------
        #| These transforms affect the position, normal, tangent, and bitangent
        #| vectors stored in a VertexArray structure, all transforms applied to
        #| any node structure, the array of bind-pose transforms stored in a
        #| Skeleton structure, and the bind-pose transform stored in a Skin
        #| structure.
        self.Write(B"#Metric (key = \"up\") {string {\"z\"}}\n")

    def execute(self, context):
        print("\n#--------------------------------------------------")
        print("# OpenGEX Exporter v0.0.0")
        print("#--------------------------------------------------")

        self.file = open(self.filepath, "wb")

        self.indentLevel = 0

        scene = context.scene
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

        self.Write(B"{\n")

        print("Processing nodes")
        for object in scene.objects:
            if (not object.parent):
                print(f"  {object.type} {object.name}")
                self.ProcessNode(object)

        self.ProcessSkinnedMeshes()

        print("Exporting nodes")
        for object in scene.objects:
            if (not object.parent):
                print(f"  {object.type} {object.name}")
                self.ExportNode(object, scene)

        print("Exporting objects")
        self.ExportObjects(scene)
        print("Exporting materials")
        self.ExportMaterials()

        self.Write(B"}\n")
        self.file.close()

        if (self.restoreFrame):
            scene.frame_set(originalFrame, subframe=originalSubframe)

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










class Image:
    def __init__(self, buffer_view, mime_type, name, uri):
        self.buffer_view = buffer_view
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
        regex_dot = re.compile(".")
        adjusted_name = re.sub(regex_dot, "_", self.name)
        new_name = "".join([char for char in adjusted_name if char not in "!#$&'()*+,/:;<>?@[\\]^`{|}~"])
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

class Sampler:
    def __init__(self, mag_filter, min_filter, name, wrap_s, wrap_t):
        self.mag_filter = mag_filter
        self.min_filter = min_filter
        self.name = name
        self.wrap_s = wrap_s
        self.wrap_t = wrap_t

class Texture:
    def __init__(self, name, sampler, source):
        self.name = name
        self.sampler = sampler
        self.source = source

class TextureInfo:
    def __init__(self, index, tex_coord):
        self.index = index
        self.tex_coord = tex_coord

    def filename(self, filepath):
        uri = self.index.source.uri
        filename = f"{filepath}_{uri.name}{uri.file_extension}"
        return filename

    def data(self):
        return self.index.source.uri.data

class Channel(enum.IntEnum):
    R = 0
    G = 1
    B = 2
    A = 3

# These describe how an ExportImage's channels should be filled.
class FillImage:
    """Fills a channel with the channel src_chan from a Blender image."""
    def __init__(self, image: bpy.types.Image, src_chan: Channel):
        self.image = image
        self.src_chan = src_chan

class FillWhite:
    """Fills a channel with all ones (1.0)."""
    pass

class ExportImage:
    """Custom image class.

    An image is represented by giving a description of how to fill its red,
    green, blue, and alpha channels. For example:

        self.fills = {
            Channel.R: FillImage(image=bpy.data.images['Im1'], src_chan=Channel.B),
            Channel.G: FillWhite(),
        }

    This says that the ExportImage's R channel should be filled with the B
    channel of the Blender image 'Im1', and the ExportImage's G channel
    should be filled with all 1.0s. Undefined channels mean we don't care
    what values that channel has.

    This is flexible enough to handle the case where eg. the user used the R
    channel of one image as the metallic value and the G channel of another
    image as the roughness, and we need to synthesize an ExportImage that
    packs those into the B and G channels for glTF.

    Storing this description (instead of raw pixels) lets us make more
    intelligent decisions about how to encode the image.
    """

    def __init__(self):
        self.fills = {}

    @staticmethod
    def from_blender_image(image: bpy.types.Image):
        export_image = ExportImage()
        for chan in range(image.channels):
            export_image.fill_image(image, dst_chan=chan, src_chan=chan)
        return export_image

    def fill_image(self, image: bpy.types.Image, dst_chan: Channel, src_chan: Channel):
        self.fills[dst_chan] = FillImage(image, src_chan)

    def fill_white(self, dst_chan: Channel):
        self.fills[dst_chan] = FillWhite()

    def is_filled(self, chan: Channel) -> bool:
        return chan in self.fills

    def empty(self) -> bool:
        return not self.fills

    def blender_image(self) -> Optional[bpy.types.Image]:
        """If there's an existing Blender image we can use,
        returns it. Otherwise (if channels need packing),
        returns None.
        """
        if self.__on_happy_path():
            for fill in self.fills.values():
                return fill.image
        return None

    def __on_happy_path(self) -> bool:
        # All src_chans match their dst_chan and come from the same image
        return (
            all(isinstance(fill, FillImage) for fill in self.fills.values()) and
            all(dst_chan == fill.src_chan for dst_chan, fill in self.fills.items()) and
            len(set(fill.image.name for fill in self.fills.values())) == 1
        )

    def encode(self, mime_type: Optional[str]) -> bytes:
        self.file_format = {
            "image/jpeg": "JPEG",
            "image/png": "PNG"
        }.get(mime_type, "PNG")

        # Happy path = we can just use an existing Blender image
        if self.__on_happy_path():
            return self.__encode_happy()

        # Unhappy path = we need to create the image self.fills describes.
        return self.__encode_unhappy()

    def __encode_happy(self) -> bytes:
        return self.__encode_from_image(self.blender_image())

    def __encode_unhappy(self) -> bytes:
        print_console("WARNING", "Taking unhappy path for ExportImage.encode().")
        result = self.__encode_unhappy_with_compositor()
        if result is not None:
            return result
        return None #self.__encode_unhappy_with_numpy()

    def __encode_unhappy_with_compositor(self) -> bytes:
        # Builds a Compositor graph that will build the correct image
        # from the description in self.fills.
        #
        #     [ Image ]->[ Sep RGBA ]    [ Comb RGBA ]
        #                [  src_chan]--->[dst_chan   ]--->[ Output ]
        #
        # This is hacky, but is about 4x faster than using
        # __encode_unhappy_with_numpy. There are some caveats though:

        # First, we can't handle pre-multiplied alpha.
        if Channel.A in self.fills:
            return None

        # Second, in order to get the same results as using image.pixels
        # (which ignores the colorspace), we need to use the 'Non-Color'
        # colorspace for all images and set the output device to 'None'. But
        # setting the colorspace on dirty images discards their changes.
        # So we can't handle dirty images that aren't already 'Non-Color'.
        for fill in self.fills:
            if isinstance(fill, FillImage):
                if fill.image.is_dirty:
                    if fill.image.colorspace_settings.name != 'Non-Color':
                        return None

        tmp_scene = None
        orig_colorspaces = {}  # remembers original colorspaces
        try:
            tmp_scene = bpy.data.scenes.new('##gltf-export:tmp-scene##')
            tmp_scene.use_nodes = True
            node_tree = tmp_scene.node_tree
            for node in node_tree.nodes:
                node_tree.nodes.remove(node)

            out = node_tree.nodes.new('CompositorNodeComposite')
            comb_rgba = node_tree.nodes.new('CompositorNodeCombRGBA')
            for i in range(4):
                comb_rgba.inputs[i].default_value = 1.0
            node_tree.links.new(out.inputs['Image'], comb_rgba.outputs['Image'])

            img_size = None
            for dst_chan, fill in self.fills.items():
                if not isinstance(fill, FillImage):
                    continue

                img = node_tree.nodes.new('CompositorNodeImage')
                img.image = fill.image
                sep_rgba = node_tree.nodes.new('CompositorNodeSepRGBA')
                node_tree.links.new(sep_rgba.inputs['Image'], img.outputs['Image'])
                node_tree.links.new(comb_rgba.inputs[dst_chan], sep_rgba.outputs[fill.src_chan])

                if fill.image.colorspace_settings.name != 'Non-Color':
                    if fill.image.name not in orig_colorspaces:
                        orig_colorspaces[fill.image.name] = \
                            fill.image.colorspace_settings.name
                    fill.image.colorspace_settings.name = 'Non-Color'

                if img_size is None:
                    img_size = fill.image.size[:2]
                else:
                    # All images should be the same size (should be
                    # guaranteed by gather_texture_info)
                    assert img_size == fill.image.size[:2]

            width, height = img_size or (1, 1)
            return _render_temp_scene(
                tmp_scene=tmp_scene,
                width=width,
                height=height,
                file_format=self.file_format,
                color_mode='RGB',
                colorspace='None',
            )

        finally:
            for img_name, colorspace in orig_colorspaces.items():
                bpy.data.images[img_name].colorspace_settings.name = colorspace

            if tmp_scene is not None:
                bpy.data.scenes.remove(tmp_scene, do_unlink=True)

    # def __encode_unhappy_with_numpy(self):
    #     # Read the pixels of each image with image.pixels, put them into a
    #     # numpy, and assemble the desired image that way. This is the slowest
    #     # method, and the conversion to Python data eats a lot of memory, so
    #     # it's only used as a last resort.
    #     result = None

    #     img_fills = {
    #         chan: fill
    #         for chan, fill in self.fills.items()
    #         if isinstance(fill, FillImage)
    #     }
    #     # Loop over images instead of dst_chans; ensures we only decode each
    #     # image once even if it's used in multiple channels.
    #     image_names = list(set(fill.image.name for fill in img_fills.values()))
    #     for image_name in image_names:
    #         image = bpy.data.images[image_name]

    #         if result is None:
    #             result = np.ones((image.size[0], image.size[1], 4), np.float32)
    #         # Images should all be the same size (should be guaranteed by
    #         # gather_texture_info).
    #         assert (image.size[0], image.size[1]) == result.shape[:2]

    #         # Slow and eats all your memory.
    #         pixels = np.array(image.pixels[:])

    #         pixels = pixels.reshape((image.size[0], image.size[1], image.channels))

    #         for dst_chan, img_fill in img_fills.items():
    #             if img_fill.image == image:
    #                 result[:, :, dst_chan] = pixels[:, :, img_fill.src_chan]

    #         pixels = None  # GC this please

    #     if result is None:
    #         # No ImageFills; use a 1x1 white pixel
    #         result = np.array([1.0, 1.0, 1.0, 1.0])
    #         result = result.reshape((1, 1, 4))

    #     return self.__encode_from_numpy_array(result)

    # def __encode_from_numpy_array(self, array: np.ndarray) -> bytes:
    #     tmp_image = None
    #     try:
    #         tmp_image = bpy.data.images.new(
    #             "##gltf-export:tmp-image##",
    #             width=array.shape[0],
    #             height=array.shape[1],
    #             alpha=Channel.A in self.fills,
    #         )
    #         assert tmp_image.channels == 4  # 4 regardless of the alpha argument above.

    #         # Also slow and eats all your memory.
    #         tmp_image.pixels = array.flatten().tolist()

    #         return _encode_temp_image(tmp_image, self.file_format)

    #     finally:
    #         if tmp_image is not None:
    #             bpy.data.images.remove(tmp_image, do_unlink=True)

    def __encode_from_image(self, image: bpy.types.Image) -> bytes:
        # See if there is an existing file we can use.
        if image.source == 'FILE' and image.file_format == self.file_format and \
                not image.is_dirty:
            if image.packed_file is not None:
                return image.packed_file.data
            else:
                src_path = bpy.path.abspath(image.filepath_raw)
                if os.path.isfile(src_path):
                    with open(src_path, 'rb') as f:
                        return f.read()

        # Copy to a temp image and save.
        tmp_image = None
        try:
            tmp_image = image.copy()
            tmp_image.update()
            if image.is_dirty:
                tmp_image.pixels = image.pixels[:]

            return _encode_temp_image(tmp_image, self.file_format)
        finally:
            if tmp_image is not None:
                bpy.data.images.remove(tmp_image, do_unlink=True)

def _encode_temp_image(tmp_image: bpy.types.Image, file_format: str) -> bytes:
    with tempfile.TemporaryDirectory() as tmpdirname:
        tmpfilename = tmpdirname + '/img'
        tmp_image.filepath_raw = tmpfilename

        tmp_image.file_format = file_format

        tmp_image.save()

        with open(tmpfilename, "rb") as f:
            return f.read()

def _render_temp_scene(
    tmp_scene: bpy.types.Scene,
    width: int,
    height: int,
    file_format: str,
    color_mode: str,
    colorspace: str,
) -> bytes:
    """Set render settings, render to a file, and read back."""
    tmp_scene.render.resolution_x = width
    tmp_scene.render.resolution_y = height
    tmp_scene.render.resolution_percentage = 100
    tmp_scene.display_settings.display_device = colorspace
    tmp_scene.render.image_settings.color_mode = color_mode
    tmp_scene.render.dither_intensity = 0.0

    # Turn off all metadata (stuff like use_stamp_date, etc.)
    for attr in dir(tmp_scene.render):
        if attr.startswith('use_stamp_'):
            setattr(tmp_scene.render, attr, False)

    with tempfile.TemporaryDirectory() as tmpdirname:
        tmpfilename = tmpdirname + "/img"
        tmp_scene.render.filepath = tmpfilename
        tmp_scene.render.use_file_extension = False
        tmp_scene.render.image_settings.file_format = file_format

        bpy.ops.render.render(scene=tmp_scene.name, write_still=True)

        with open(tmpfilename, "rb") as f:
            return f.read()






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
def get_material_socket(blender_material: bpy.types.Material, name: str):
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
    emissive_socket = get_material_socket(blender_material, "Emissive")
    if isinstance(emissive_socket, bpy.types.NodeSocket):
        if emissive_socket.is_linked:
            # In glTF, the default emissiveFactor is all zeros, so if an emission texture is connected,
            # we have to manually set it to all ones.
            return [1.0, 1.0, 1.0]
        else:
            return list(emissive_socket.default_value)[0:3]
    return None

def gather_emissive_texture(blender_material):
    emissive = get_material_socket(blender_material, "Emissive")
    return gather_texture_info(emissive)

def gather_normal_factor(blender_material):
    normal_socket = get_material_socket(blender_material, "Normal")
    if isinstance(normal_socket, bpy.types.NodeSocket):
        if normal_socket.is_linked:
            return [1.0, 1.0, 1.0]
        else:
            return normal_socket.default_value
    return None

    # TODO(dlb): Do we care about normal factor (i.e. "strength")?
    # normal_map = from_socket(socket, bpy.types.ShaderNodeNormalMap)
    # if not normal_map:
    #     return None
    # strengthInput = normal_map[0].shader_node.inputs['Strength']
    # if not strengthInput.is_linked and strengthInput.default_value != 1:
    #     return strengthInput.default_value

def gather_normal_texture(blender_material):
    normal = get_material_socket(blender_material, "Normal")
    return gather_texture_info(normal)

def get_tex_from_socket(socket: bpy.types.NodeSocket):
    tex = from_socket(socket, bpy.types.ShaderNodeTexImage)
    if not tex:
        return None
    if tex[0].shader_node.image is None:
        return None
    return tex[0]

def gather_alpha_factor(blender_material):
    alpha_socket = get_material_socket(blender_material, "Alpha")
    if alpha_socket and not alpha_socket.is_linked:
        return alpha_socket.default_value
    return None

def gather_alpha_texture(blender_material):
    alpha_socket = get_material_socket(blender_material, "Alpha")
    return gather_texture_info(alpha_socket)

def gather_albedo_factor(blender_material):
    albedo_socket = get_material_socket(blender_material, "Base Color")
    if albedo_socket and not albedo_socket.is_linked:
        return list(albedo_socket.default_value)

    tex = get_tex_from_socket(albedo_socket)
    if not tex:
        return None

    def is_valid_multiply_node(node):
        return isinstance(node, bpy.types.ShaderNodeMixRGB) and \
            node.blend_type == "MULTIPLY" and \
            len(node.inputs) == 3

    multiply_node = next((link.from_node for link in tex.path if is_valid_multiply_node(link.from_node)), None)
    if multiply_node is None:
        return None

    def is_factor_socket(socket):
        return isinstance(socket, bpy.types.NodeSocketColor) and \
            (not socket.is_linked or socket.links[0] not in tex.path)

    factor_socket = next((socket for socket in multiply_node.inputs if is_factor_socket(socket)), None)
    if factor_socket is None:
        return None

    if factor_socket.is_linked:
        print_console("WARNING", "BaseColorFactor only supports sockets without links (in Node '{}')."
                    .format(multiply_node.name))
        return None

    return list(factor_socket.default_value)

def gather_albedo_texture(blender_material):
    albedo_socket = get_material_socket(blender_material, "Base Color")
    return gather_texture_info(albedo_socket)

def gather_metallic_factor(blender_material):
    metallic_socket = get_material_socket(blender_material, "Metallic")
    if metallic_socket and not metallic_socket.is_linked:
        return metallic_socket.default_value
    return None

def gather_metallic_texture(blender_material):
    metallic_socket = get_material_socket(blender_material, "Metallic")
    return gather_texture_info(metallic_socket)

def gather_roughness_factor(blender_material):
    roughness_socket = get_material_socket(blender_material, "Roughness")
    if roughness_socket and not roughness_socket.is_linked:
        return roughness_socket.default_value
    return None

def gather_roughness_texture(blender_material):
    roughness_socket = get_material_socket(blender_material, "Roughness")
    return gather_texture_info(roughness_socket)





def gather_texture_info(socket: bpy.types.NodeSocket):
    texture_info = TextureInfo(
        index=gather_texture(socket),
        tex_coord=gather_tex_coord(socket)
    )

    if texture_info.index is None:
        return None

    return texture_info

def gather_tex_coord(socket: bpy.types.NodeSocket):
    tex = get_tex_from_socket(socket)
    if not tex:
        return 0

    if len(tex.shader_node.inputs['Vector'].links) == 0:
        return 0

    input_node = tex.shader_node.inputs['Vector'].links[0].from_node

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
    if not start_socket:
        return None
    if not isinstance(start_socket, bpy.types.NodeSocket):
        return None

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





def gather_texture(socket: bpy.types.NodeSocket):
    """
    Gather texture sampling information and image channels from a blender shader texture attached to a shader socket.

    :param socket: The socket of the material which should contribute to the texture
    :return: a glTF 2.0 texture with sampler and source embedded (will be converted to references by the exporter)
    """
    texture = Texture(
        name=None,
        sampler=gather_sampler(socket),
        source=gather_image(socket)
    )

    # although valid, most viewers can't handle missing source properties
    if texture.source is None:
        return None

    return texture



def gather_sampler(socket: bpy.types.NodeSocket):
    tex = get_tex_from_socket(socket)
    if not tex:
        return None
    if not gather_sampler_filter(tex.shader_node):
        return None

    sampler = Sampler(
        mag_filter=gather_sampler_mag_filter(tex.shader_node),
        min_filter=gather_sampler_min_filter(tex.shader_node),
        name=None,
        wrap_s=gather_sampler_wrap_s(tex.shader_node),
        wrap_t=gather_sampler_wrap_t(tex.shader_node)
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





def gather_image(socket: bpy.types.NodeSocket):
    image_data = gather_image_data(socket)
    if not image_data or image_data.empty():
        return None

    mime_type = "image/png"
    name = gather_image_name(socket)
    image = Image(
        buffer_view=gather_image_buffer_view(image_data, mime_type, name),
        mime_type=mime_type,
        name=name,
        uri=gather_image_uri(image_data, mime_type, name)
    )

    return image

def gather_image_buffer_view(image_data, mime_type, name):
    # TODO(dlb): Separate vs. embedded images?
    # if export_settings[gltf2_blender_export_keys.FORMAT] != 'GLTF_SEPARATE':
    #     return gltf2_io_binary_data.BinaryData(data=image_data.encode(mime_type))
    return None

def gather_image_name(socket: bpy.types.NodeSocket):
    combined_name = None
    foundNames = []

    # TODO(dlb): Hoist this out into caller, we're not passing multiple sockets this deep anymore
    sockets = [socket]
    # If multiple images are being combined, combine the names as well.
    for socket in sockets:
        tex = get_tex_from_socket(socket)
        if tex is not None:
            image_name = tex.shader_node.image.name
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

def gather_image_data(socket: bpy.types.NodeSocket) -> ExportImage:
    # For shared resources, such as images, we just store the portion of data that is needed in the glTF property
    # in a helper class. During generation of the glTF in the exporter these will then be combined to actual binary
    # resources.
    tex = get_tex_from_socket(socket)
    if not tex:
        return None

    if tex.shader_node.image.channels == 0:
        gltf2_io_debug.print_console("WARNING",
            f"Image '{tex.shader_node.image}' has no color channels and cannot be exported.")
        return None

    # rudimentarily try follow the node tree to find the correct image data.
    src_chan = Channel.R
    for elem in tex.path:
        if isinstance(elem.from_node, bpy.types.ShaderNodeSeparateRGB):
            src_chan = {
                'R': Channel.R,
                'G': Channel.G,
                'B': Channel.B,
            }[elem.from_socket.name]
        if elem.from_socket.name == 'Alpha':
            src_chan = Channel.A

    dst_chan = None

    # TODO(dlb): We may want to combine channels in the exporter? Probably not exactly like glTF though..
    # # some sockets need channel rewriting (gltf pbr defines fixed channels for some attributes)
    # if socket.name == 'Metallic':
    #     dst_chan = Channel.B
    # elif socket.name == 'Roughness':
    #     dst_chan = Channel.G
    # elif socket.name == 'Occlusion' and len(sockets_or_slots) > 1 and sockets_or_slots[1] is not None:
    #     dst_chan = Channel.R
    # elif socket.name == 'Alpha' and len(sockets_or_slots) > 1 and sockets_or_slots[1] is not None:
    #     dst_chan = Channel.A

    composed_image = ExportImage()
    if dst_chan is not None:
        composed_image.fill_image(tex.shader_node.image, dst_chan, src_chan)

        # Since metal/roughness are always used together, make sure
        # the other channel is filled.
        if socket.name == 'Metallic' and not composed_image.is_filled(Channel.G):
            composed_image.fill_white(Channel.G)
        elif socket.name == 'Roughness' and not composed_image.is_filled(Channel.B):
            composed_image.fill_white(Channel.B)
    else:
        # copy full image...eventually following sockets might overwrite things
        composed_image = ExportImage.from_blender_image(tex.shader_node.image)

    return composed_image




if __name__ == "__main__":
    register()

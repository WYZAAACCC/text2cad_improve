"""Geometry utility helpers — OCP-native 3D wire, pipe, and safe boolean operations.

All functions use OCP (OpenCascade Python) native API, bypassing CadQuery
limitations (XY-plane workplane, sweep Z-dropping, parametricCurve approximation).
"""

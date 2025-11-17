#!/usr/bin/env python3
# Generates a PNG visualizing the reflection vector (debugReflectionMode = 1)
# Colors = normalize(r) * 0.5 + 0.5  (R = x, G = y, B = z mapped from [-1,1] to [0,1])
# Requires: pip install numpy pillow

import math
import numpy as np
from PIL import Image

W = 1024
H = 1024
aspect = W / H

# camera
cam_z = 2.0  # camera position on z axis
cam_pos = np.array([0.0, 0.0, cam_z], dtype=np.float32)

# sphere in world space
sphere_center = np.array([0.0, 0.0, 0.0], dtype=np.float32)
sphere_radius = 1.0

# rotation around Y (horizontal) in degrees
ANGLE_DEGREES = 60.0
_angle = math.radians(ANGLE_DEGREES)
_cos_a = math.cos(_angle)
_sin_a = math.sin(_angle)

# image plane mapping (NDC-like)
fov = math.radians(45.0)
# place image plane at z = 1.0 units in front of camera (not strictly needed for this calc)
# we'll map pixel to [-1,1] range preserving aspect
sx = 2.0 / W
sy = 2.0 / H

img = np.zeros((H, W, 3), dtype=np.uint8)

for j in range(H):
    # normalized y coordinate (top->bottom)
    y_ndc = (1.0 - (j + 0.5) / H) * 2.0 - 1.0
    for i in range(W):
        x_ndc = ((i + 0.5) / W) * 2.0 - 1.0
        x = x_ndc * aspect  # preserve aspect
        y = y_ndc

        # Ray from camera through pixel (simple pinhole)
        # direction in camera space:
        ray_dir = np.array([x, y, -1.0], dtype=np.float32)
        ray_dir = ray_dir / np.linalg.norm(ray_dir)

        # Ray-sphere intersection (camera at cam_pos, ray_dir)
        o = cam_pos - sphere_center
        b = 2.0 * np.dot(ray_dir, o)
        c = np.dot(o, o) - sphere_radius * sphere_radius
        disc = b * b - 4.0 * c
        if disc < 0:
            # no intersection -> background (use neutral gray)
            img[j, i] = (128, 128, 128)
            continue

        t0 = (-b - math.sqrt(disc)) * 0.5
        t1 = (-b + math.sqrt(disc)) * 0.5
        t = t0 if t0 > 1e-4 else t1
        if t <= 1e-4:
            img[j, i] = (128, 128, 128)
            continue

        # intersection point
        p = cam_pos + ray_dir * t
        # normal at point
        n = (p - sphere_center)
        n = n / np.linalg.norm(n)

        # view vector pointing to camera
        v = (cam_pos - p)
        v = v / np.linalg.norm(v)

        # reflection vector r = reflect(-v, n) = reflect(I, N) where I = -v
        I = -v
        r = I - 2.0 * np.dot(I, n) * n

        # rotate reflection vector around Y by ANGLE_DEGREES
        rx = _cos_a * r[0] + _sin_a * r[2]
        ry = r[1]
        rz = -_sin_a * r[0] + _cos_a * r[2]
        r = np.array([rx, ry, rz], dtype=np.float32)

        # visualize `normalize(r) * 0.5 + 0.5`
        r_norm = r / (np.linalg.norm(r) + 1e-12)
        viz = (r_norm * 0.5 + 0.5) * 255.0
        viz = np.clip(viz, 0, 255)
        img[j, i] = viz.astype(np.uint8)

# save
out_name = 'debug_reflection_sphere_rotated.png'
Image.fromarray(img, 'RGB').save(out_name)
print(f'Saved {out_name}')
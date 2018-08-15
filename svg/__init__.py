#!/usr/bin/env python

import sys
import xml.etree.ElementTree as ET
import shapes as shapes_pkg
from shapes import point_generator
def get_aspect_ratio(svg_path):
    tree = ET.parse(svg_path)
    root = tree.getroot()

    width = root.get('width')
    height = root.get('height')
    if width == None or height == None:
        viewbox = root.get('viewBox')
        if viewbox:
            _, _, width, height = viewbox.split()

    if width == None or height == None:
	raise Exception("Unable to get height or width from SVG")
    width = float(''.join(filter(lambda x: x.isdigit(), width)))
    height = float(''.join(filter(lambda x: x.isdigit(), height)))
    return width/height
def get_size(svg_path):
    tree = ET.parse(svg_path)
    root = tree.getroot()

    width = root.get('width')
    height = root.get('height')
    if width == None or height == None:
        viewbox = root.get('viewBox')
        if viewbox:
            _, _, width, height = viewbox.split()

    if width == None or height == None:
	raise Exception("Unable to get height or width from SVG")
    width = float(''.join(filter(lambda x: x.isdigit(), width)))
    height = float(''.join(filter(lambda x: x.isdigit(), height)))
    return width, height

def generate_points(svg_path, smoothness=0.2):
    svg_shapes = set(['rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon', 'path'])

    tree = ET.parse(svg_path)
    root = tree.getroot()

    for elem in root.iter():
        try:
            _, tag_suffix = elem.tag.split('}')
        except ValueError:
            continue

        if tag_suffix in svg_shapes:
            shape_class = getattr(shapes_pkg, tag_suffix)
            shape_obj = shape_class(elem)
            d = shape_obj.d_path()
            m = shape_obj.transformation_matrix()

            if d:
                p = point_generator(d, m, smoothness)
               	yield p





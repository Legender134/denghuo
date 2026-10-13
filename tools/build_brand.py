"""Export the vector lantern to aligned Windows icon frames.

The web SVG is the brand master. This exporter supports only its rect and
orthogonal filled paths; unsupported geometry stops the build explicitly.
Pillow is a development dependency, never required by the application.
"""
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]


def polygons(path):
    tokens = re.findall(r'[MmHhVvZz]|-?\d+(?:\.\d+)?', path)
    if ''.join(tokens) != re.sub(r'[\s,]', '', path):
        raise ValueError('Brand export supports only orthogonal SVG paths')
    point = [0.0, 0.0]
    contour = []
    result = []
    index = 0
    while index < len(tokens):
        command = tokens[index]; index += 1
        if command in 'Zz':
            result.append(contour)
            point = list(contour[0]); contour = []
            continue
        dimensions = 2 if command in 'Mm' else 1
        values = [float(value) for value in tokens[index:index+dimensions]]
        index += dimensions
        if command in 'Mm':
            if contour: result.append(contour)
            point = [point[i]+values[i] if command == 'm' else values[i] for i in range(2)]
            contour = [tuple(point)]
        else:
            axis = 0 if command in 'Hh' else 1
            point[axis] = point[axis]+values[0] if command.islower() else values[0]
            contour.append(tuple(point))
    if contour: result.append(contour)
    return result


def render(size):
    image = Image.new('RGBA', (size, size))
    draw = ImageDraw.Draw(image)
    vector = ET.parse(ROOT/'web/icon.svg').getroot()
    for element in vector:
        tag = element.tag.rsplit('}', 1)[-1]
        fill = element.attrib['fill']
        if tag == 'rect':
            draw.rounded_rectangle((0, 0, size-1, size-1), radius=round(size*float(element.attrib.get('rx', 0))/64), fill=fill)
        elif tag == 'path':
            for points in polygons(element.attrib['d']):
                draw.polygon([(round(x*size/64), round(y*size/64)) for x,y in points], fill=fill)
        else:
            raise ValueError('Unsupported brand geometry: '+tag)
    return image


def main():
    sizes = (16, 20, 24, 32, 40, 48, 64, 128, 256)
    frames = [render(size) for size in sizes]
    frames[-1].save(ROOT/'data/lamp.png')
    frames[-1].save(ROOT/'data/lamp.ico', sizes=[(size,size) for size in sizes], append_images=frames[:-1])


if __name__ == '__main__':
    main()

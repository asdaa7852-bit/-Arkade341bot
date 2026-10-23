"""Small dependency-free animated badge compositor (GIF89a)."""
import math
import struct

PALETTE = [(10, 12, 24), (29, 33, 54), (235, 187, 72), (255, 230, 156),
           (246, 76, 56), (255, 154, 55), (103, 203, 255), (191, 232, 255),
           (151, 124, 255), (222, 211, 255), (112, 224, 179), (242, 246, 255),
           (54, 60, 91), (113, 123, 161), (255, 119, 176), (89, 55, 65)]


def render(items):
    """Return a single looping GIF with one to four distinct decorations."""
    items = list(dict.fromkeys(items))[:4]
    if not items:
        raise ValueError('No decorations')
    size = 224
    out = bytearray(b'GIF89a' + struct.pack('<HHBBB', size, size, 0xF3, 0, 0))
    out.extend(bytes(c for rgb in PALETTE for c in rgb))
    out.extend(b'!\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00')
    for frame in range(16):
        pixels = bytearray(size*size)

        def dot(x, y, color):
            x, y = int(x), int(y)
            if 0 <= x < size and 0 <= y < size:
                pixels[y*size+x] = color

        def circle(x, y, radius, color):
            for yy in range(int(y-radius), int(y+radius)+1):
                for xx in range(int(x-radius), int(x+radius)+1):
                    if (xx-x)**2+(yy-y)**2 <= radius**2:
                        dot(xx, yy, color)

        def line(x1, y1, x2, y2, color, width=1):
            steps = max(abs(int(x2-x1)), abs(int(y2-y1)), 1)
            for step in range(steps+1):
                circle(x1+(x2-x1)*step/steps, y1+(y2-y1)*step/steps, width, color)

        def poly(points, color):
            for y in range(max(0, int(min(p[1] for p in points))), min(size, int(max(p[1] for p in points))+1)):
                xs = []
                for i, (x1, y1) in enumerate(points):
                    x2, y2 = points[(i+1) % len(points)]
                    if min(y1, y2) <= y < max(y1, y2):
                        xs.append(x1+(y-y1)*(x2-x1)/(y2-y1))
                xs.sort()
                for left, right in zip(xs[::2], xs[1::2]):
                    for x in range(int(left), int(right)+1): dot(x, y, color)

        # One shared moving halo joins all equipped decorations.
        for radius in (65, 96):
            for n in range(180):
                angle = n*math.tau/180
                dot(112+radius*math.cos(angle), 112+radius*math.sin(angle), 2 if (n+frame*3)%30 < 4 else 12)
        circle(112, 112, 38, 1)
        circle(112, 112, 33, 15)
        poly([(91,119),(87,97),(102,107),(112,90),(122,107),(137,97),(133,119)], 2)
        line(94,126,130,126,3,2)
        for n in range(12):
            a = (n/12+frame/128)*math.tau
            r = 43+(n%3)*4
            circle(112+r*math.cos(a),112+r*math.sin(a),1,3 if (n+frame)%4==0 else 12)
        for index, item in enumerate(items):
            angle = -math.pi/2+index*math.tau/len(items)+math.sin(frame*math.tau/16)*0.06
            x,y = 112+76*math.cos(angle),112+76*math.sin(angle)
            line(112+38*math.cos(angle),112+38*math.sin(angle),x,y,12)
            circle(x,y,25,2);circle(x,y,22,1)
            pulse = 2 if (frame+index*4)%16 < 5 else 0
            circle(x-18,y-17,2+pulse,3)
            if item == 'diamond':
                poly([(x-15,y-5),(x-8,y-14),(x+8,y-14),(x+15,y-5),(x,y+17)],6)
                line(x-15,y-5,x+15,y-5,7);line(x-8,y-14,x,y+17,7);line(x+8,y-14,x,y+17,7)
            elif item == 'fire':
                poly([(x,y-18),(x+5,y-5),(x+11,y-10),(x+15,y+5),(x+8,y+16),(x-9,y+16),(x-15,y+5),(x-8,y-6),(x-5,y+2)],4)
                poly([(x,y-7),(x+8,y+8),(x+3,y+16),(x-5,y+16),(x-8,y+8)],5)
            elif item == 'wolf':
                poly([(x-16,y-16),(x-5,y-8),(x+5,y-8),(x+16,y-16),(x+13,y+7),(x,y+18),(x-13,y+7)],13)
                poly([(x-11,y-2),(x-4,y),(x-6,y+4)],7);poly([(x+11,y-2),(x+4,y),(x+6,y+4)],7)
                poly([(x-4,y+9),(x+4,y+9),(x,y+14)],11)
            elif item == 'survivor':
                poly([(x-14,y-12),(x,y-18),(x+14,y-12),(x+11,y+7),(x,y+18),(x-11,y+7)],10)
                line(x-7,y,x-1,y+6,11,2);line(x-1,y+6,x+9,y-6,11,2)
            elif item == 'raider':
                line(x-13,y-14,x+12,y+13,11,3);line(x+13,y-14,x-12,y+13,11,3)
                line(x-15,y+5,x-5,y+15,2,2);line(x+15,y+5,x+5,y+15,2,2)
            else:
                poly([(x-14,y+8),(x-17,y-11),(x-6,y-3),(x,y-17),(x+6,y-3),(x+17,y-11),(x+14,y+8)],8)
                line(x-13,y+14,x+13,y+14,9,2)
        # Literal LZW blocks, reset before code width grows: portable, bounded.
        codes = []
        for pos in range(0, len(pixels), 200):
            codes.append(256); codes.extend(pixels[pos:pos+200])
        codes.append(257)
        packed = bytearray(); bits = count = 0
        for code in codes:
            bits |= code << count; count += 9
            while count >= 8:
                packed.append(bits & 255); bits >>= 8; count -= 8
        if count: packed.append(bits & 255)
        out.extend(b'!\xf9\x04\x04\x08\x00\x00\x00')
        out.extend(b',' + struct.pack('<HHHHB', 0, 0, size, size, 0) + b'\x08')
        for pos in range(0, len(packed), 255):
            chunk = packed[pos:pos+255]; out.append(len(chunk)); out.extend(chunk)
        out.append(0)
    out.append(0x3B)
    return bytes(out)

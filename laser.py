from PIL import Image
import io, traceback, sys, json, magic
import logging, base64
import argparse
from fractions import Fraction
import xml.etree.cElementTree as et
import cairosvg
import tempfile
LASER_ON = "M42 P44 S%s"
LASER_OFF = "M42 P44 S0"


def is_svg(filename):
    tag = None
    with open(filename, "r") as f:
        try:
            for event, el in et.iterparse(f, ('start',)):
                tag = el.tag
                break
        except et.ParseError:
            pass
        except UnicodeDecodeError:
            return False
    return tag == '{http://www.w3.org/2000/svg}svg'


def translate_power_value(value, max_power):
	leftMin = 0
	leftMax = 100
	rightMin = 0
	rightMax = max_power
	# Figure out how 'wide' each range is
	leftSpan = leftMax - leftMin
	rightSpan = rightMax - rightMin

	# Convert the left range into a 0-1 range (float)
	valueScaled = float(value - leftMin) / float(leftSpan)

	# Convert the 0-1 range into a value in the right range.
	return rightMin + (valueScaled * rightSpan)

def pairs(l):
    return [l[i:i + 2] for i in range(0, len(l), 2)]
def starts(row):
	return [pixel for index, pixel in enumerate(row) if (pixel[2] <= 128 and row[index-1][2] > 128) ]
def stops(row):
	return [pixel for index, pixel in enumerate(row[:-1]) if (pixel[2] <= 128 and row[index+1][2] > 128) ]
def starts_and_stops(row):
	index = row[0][1]
	return [p for p in pairs(sorted(starts(row) + stops(row), key=lambda x: x[0])) if len(p) == 2]
def to_gcode(row, origin, units_per_pixel, feed_rate, travel_rate, power):
	startsandstops = starts_and_stops(row)
	start_code = LASER_ON % power
	return ["G0 X%.10f F%d\n%s\nG0 X%.10f F%d\n%s\n" % (((start[0] - origin[0]) * units_per_pixel), travel_rate, start_code, ((stop[0]-origin[0]) * units_per_pixel), feed_rate, LASER_OFF) for start, stop in startsandstops]

def bitmap_mode(options):
	targetDPI = options.dpi
	height = options.height
	width = options.width
	units = options.units


	mime = magic.from_file(options.imagefile, mime=True)
	if is_svg(options.imagefile):
		new_file, filename = tempfile.mkstemp()
		cairosvg.svg2png(url=options.imagefile, scale=20.0,  dpi=500, write_to=filename)
		options.imagefile = filename

	im = Image.open(options.imagefile)
	x, y = im.size

	if height and not width:
		if options.units == "mm":
			height = height/25.4
		DPI = y/height
		width = x / DPI
	if width and not height:
		if options.units == "mm":
			width = width/25.4
		DPI = x/width
		height = y / DPI

	newPixelsHeight = int(height*targetDPI)
	newPixelsWidth = int(width*targetDPI)
	logging.debug("(%s, %s) (%s, %s)" % (height, width, x, y))
	logging.debug("Image size (px): %d x %d" % (newPixelsHeight, newPixelsWidth))
	im = im.resize((newPixelsHeight, newPixelsWidth))
	im = im.transpose(Image.FLIP_TOP_BOTTOM) # flip 
	#convert to grayscale
	im = im.convert("RGBA")
	canvas = Image.new('RGBA', im.size, (255, 255, 255, 255))  # Empty canvas colour (r,g,b,a)
	canvas.paste(im, mask=im)
	gray = canvas.convert('L')
	bw = gray.point(lambda x: 0 if x < 128 else 255, '1')
	pixels = bw.load()
#	pixels = im.load()
	if options.units == "mm":
		units_per_pixel = (height/newPixelsHeight)*25.4
	else:
		units_per_pixel = height/newPixelsHeight
	logging.debug("Units Per Pixel: %.4f" % (units_per_pixel))
	logging.debug("Final Image size (units): %.2f x %.2f" % (newPixelsHeight*units_per_pixel, newPixelsWidth*units_per_pixel))
	if options.origin == "center":
		origin = (x/2, y/2)
	elif options.origin == "left-lower":
		origin = 0, 0
	elif options.origin == "left-upper":
		origin = 0, y
	elif options.origin == "right-lower":
		origin = x, 0
	elif options.origin == "right-upper":
		origin = x, y

	output = []
	if options.home_before:
		if options.home_z:
			output.append("G28 X Y Z")
		else:
			output.append("G28 X Y")


	if options.bounding_box:
		logging.info("Generatring code for bounding box")
		start_code = LASER_ON % translate_power_value(options.power, options.max_power)
		output.append("G0 X%.5f Y%.5f F%d\n" % (0-origin[0]+options.offset_x, 0-origin[1]+options.offset_y, options.travel_rate))
		output.append("%s\n" % start_code)
		output.append("G0 X%.5f Y%.5f F%d\n" % (((x-origin[0])*units_per_pixel)+options.offset_x, 0-origin[1]+options.offset_y, options.feed_rate))
		output.append("G0 X%.5f Y%.5f F%d\n" % (((x-origin[0])*units_per_pixel)+options.offset_x, ((y-origin[1])*units_per_pixel)+options.offset_y, options.feed_rate))
		output.append("G0 X%.5f Y%.5f F%d\n" % (0-origin[0]+options.offset_x, ((y-origin[1])*units_per_pixel)+options.offset_y, options.feed_rate))
		output.append("G0 X%.5f Y%.5f F%d\n" % (0-origin[0]+options.offset_x, 0-origin[1]+options.offset_y, options.feed_rate))
		output.append("%s\n" % LASER_OFF)

	if options.blank:
		logging.info("Blank option is set; not generating code for image")
	else:
		logging.info("Generating code for image")
		for y in range(im.size[1]):
			output.append("G0 Y%.5f\n" % ((y - origin[1]) * units_per_pixel))
			row = [(i, y, pixels[i, y]) for i in range(im.size[0])]
			new_codes = to_gcode(row, origin, units_per_pixel, options.feed_rate, options.travel_rate, translate_power_value(options.power, options.max_power))
			#if len(new_codes) > 0:
			#	logging.debug(new_codes)
			output.extend(new_codes)
	if options.home_after:
		if options.home_z:
			output.append("G28 X Y Z")
		else:
			output.append("G28 X Y")


	logging.info("Writing to file %s" % options.outputfile)
	with open(options.outputfile, 'w') as f:
#		if options.debug:
#			sys.stdout.writelines(output)
		f.writelines(output)

def vector_mode(options):
	from svg import generate_points, get_aspect_ratio, get_size
	start_code = LASER_ON % translate_power_value(options.power, options.max_power)
	end_code = LASER_OFF

	if not (options.height or options.width):
		raise Exception("You must specify either a height or width")
	aspect_ratio = get_aspect_ratio(options.imagefile)
	if options.width and not options.height:
		options.height = options.width/aspect_ratio
	if options.height and not options.width:
		options.width = options.height*aspect_ratio
	o_width, o_height = get_size(options.imagefile)

	logging.info("Aspect Ratio: %.3f or %s" % (aspect_ratio, str(Fraction(aspect_ratio).limit_denominator()).replace("/", ":")))
	logging.info("Original Dimensions: %d %s x %d %s" % (o_width, options.units, o_height, options.units))
	logging.info("Final Dimensions: %.2f %s x %.2f %s" % (options.width, options.units, options.height, options.units))

	scale_x = options.width/o_width
	scale_y = options.height/o_height
	logging.debug("Scaling Factors: %.2f %.2f" % (scale_x, scale_y))
	if options.origin == "center":
		origin = ((options.width)/2, (options.height)/2)
	elif options.origin == "left-lower":
		origin = 0, 0
	elif options.origin == "left-upper":
		origin = 0, options.height
	elif options.origin == "right-lower":
		origin = options.width, 0
	elif options.origin == "right-upper":
		origin = options.width, options.height
	logging.info("Origin Point: %.2f, %.2f" % origin)
	output = []
	if options.home_before:
		if options.home_z:
			output.append("G28 X Y Z")
		else:
			output.append("G28 X Y")

	if options.bounding_box:
		logging.info("Generating code for bounding box")
		output.append("G0 X%.5f Y%.5f\n" % (0-origin[0], 0-origin[1]))
		output.append("%s\n" % (start_code))
		output.append("G0 X%.5f Y%.5f\n" % (options.width-origin[0], 0-origin[1]))
		output.append("G0 X%.5f Y%.5f\n" % (options.width-origin[0], options.height-origin[1]))
		output.append("G0 X%.5f Y%.5f\n" % (0-origin[0], options.height-origin[1]))
		output.append("G0 X%.5f Y%.5f\n" % (0-origin[0], 0-origin[1]))
		output.append("%s\n" % end_code)
	if options.blank:
		logging.info("Blank option is set; not generating code for image")
	else:
		logging.info("Generating code for image")
		for points in generate_points(options.imagefile):
			for index, (x, y) in enumerate(points):
				if index == 0:
					output.append("G0 X%s Y%s F%d\n" % ((x*scale_x)-origin[0]+options.offset_x, (y*scale_y*-1)+(o_height*scale_y)-origin[1]+options.offset_y, options.travel_rate))
					output.append("%s\n" % start_code)
				else:
					output.append("G0 X%s Y%s F%d\n" % ((x*scale_x)-origin[0]+options.offset_x, (y*scale_y*-1)+(o_height*scale_y)-origin[1]+options.offset_y, options.feed_rate))
			output.append("%s\n" % end_code)
	if options.home_after:
		if options.home_z:
			output.append("G28 X Y Z")
		else:
			output.append("G28 X Y")
	logging.info("Writing to file %s" % options.outputfile)
	with open(options.outputfile, 'w') as f:
		f.writelines(output)

def main():
	parser = argparse.ArgumentParser(description='Generate GCode for Laser')
	parser.add_argument("mode", choices=["text", "raster", "vector"]) #bitmap and vector implemented
	parser.add_argument('-f','--feed-rate', action="store", type=int, default=300) #implemented
	parser.add_argument('-p', '--power', action="store",type=int, default=100) #implemented
	parser.add_argument('-t', '--travel-rate', action="store",type=int, default=3000) #implemented
	parser.add_argument('--height', action="store",type=float) #implemented
	parser.add_argument('--width', action="store",type=float) #implemented
	parser.add_argument('--bounding-box', action="store_true") #implemented (vector and bitmap)
	parser.add_argument('--blank', action="store_true") #implemented 
	parser.add_argument('--text', action="store") #TODO
	parser.add_argument('--font-size', action="store", type=int) #TODO
	parser.add_argument('--origin', action="store", default="left-lower", choices=["left-lower", 'right-lower', 'center', 'left-upper', 'right-lower']) #implemented
	parser.add_argument('--home-after', action="store_true") #implemented
	parser.add_argument('--home-z', action="store_true", default=False) #implemented
	parser.add_argument('--home-before', action="store_true") #implemented
	parser.add_argument('--set-zero', action="store_true") #TODO
	parser.add_argument('--debug', action="store_true") #implemented
	parser.add_argument('--units', action="store", default="mm", choices=["mm", "in"]) #implemented
	parser.add_argument('--dpi', action="store", type=float, default=250.0) #implemented
	parser.add_argument('--max-power', action="store", type=int, default=255)  #implemented
	parser.add_argument('--offset-x', action="store", type=float, default=0.0) #implemented
	parser.add_argument('--offset-y', action="store", type=float, default=0.0) #implemented
	parser.add_argument('imagefile', action="store")
	parser.add_argument('outputfile', action="store")

	args = parser.parse_args()

	if args.debug:
		logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s %(message)s')
	else:
		logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
	print(args)
	if args.mode == "raster":
		bitmap_mode(args)
	elif args.mode == "vector":

		vector_mode(args)

if __name__ == "__main__":
	main()

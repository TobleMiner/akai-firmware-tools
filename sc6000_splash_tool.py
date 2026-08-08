#!/usr/bin/env python3

import click
import os

from PIL import Image

SPLASH_WIDTH = 800
SPLASH_HEIGHT = 1280
SPLASH_SIZE = (SPLASH_WIDTH, SPLASH_HEIGHT)

@click.group(help='Tool to import and export SC6000 splash screens')
def cli():
	pass

@cli.command(help='Export splash to image file')
@click.argument('infile')
@click.argument('outfile')
def splash2image(infile, outfile):
	file_size = os.path.getsize(infile)
	if file_size != SPLASH_WIDTH * SPLASH_HEIGHT * 4:
		print(f'Invalid input file size, expected {SPLASH_SIZE} size image in 8-bit RGBA format')
		return 1
	with open(infile, 'rb') as f:
		img = Image.frombuffer('RGBA', SPLASH_SIZE, f.read())
	img.save(outfile)

@cli.command(help='Export image to splash file')
@click.argument('infile')
@click.argument('outfile')
def image2splash(infile, outfile):
	img = Image.open(infile)
	if img.size != SPLASH_SIZE:
		print(f'Invalid input image size, expected {SPLASH_SIZE}')
		return 1
	with open(outfile, 'wb') as f:
		f.write(img.tobytes())

if __name__ == '__main__':
	cli()

#!/usr/bin/env python3

import click
import hashlib
import os
import struct

from dataclasses import dataclass

def align_up(x, alignment=8):
	return (x + (alignment - 1)) & ~(alignment -1)

class BinaryStreamReader:
	def __init__(self, stream):
		self.stream = stream
		self.position = 0

	def read_u32(self):
		data = self.stream.read(4)
		if data is None or len(data) != 4:
			raise EOFError()
		self.position += 4
		return int.from_bytes(data, byteorder='little')

	def read_u64(self):
		data = self.stream.read(8)
		if data is None or len(data) != 8:
			raise EOFError()
		self.position += 8
		return int.from_bytes(data, byteorder='little')

	def read_str(self, alignment=4):
		# Strings are stored implicity nul-terminated, length does not contain null byte
		str_len = self.read_u32() + 1
		data = self.read(str_len)
		if data is None or len(data) != str_len:
			raise EOFError()
		self.align(alignment)
		return data[:-1] # Omit trailing nul byte

	def read(self, size):
		data = self.stream.read(size)
		if data is None or len(data) != size:
			raise EOFError()
		self.position += size
		return data

	def seek(self, offset):
		self.stream.seek(offset, os.SEEK_CUR)
		self.position += offset

	def align(self, alignment=8):
		self.seek(self.get_aligned_size(0, alignment))

	def get_aligned_size(self, size, alignment=8):
		return size + (alignment - (self.position + size) % alignment) % alignment

class BinaryStreamWriter:
	def __init__(self, stream):
		self.stream = stream
		self.position = 0

	def write_u32(self, val):
		self.write(val.to_bytes(length=4, byteorder='little'))

	def write_u64(self, val):
		self.write(val.to_bytes(length=8, byteorder='little'))

	def write_str(self, str, alignment=4):
		self.write_u32(len(str))
		self.write(str + b'\x00')
		self.align(alignment)

	def write(self, data):
		self.stream.write(data)
		self.position += len(data)

	def align(self, alignment=8, pad=b'\x00'):
		assert len(pad) == 1
		aligned_pos = align_up(self.position, alignment)
		assert aligned_pos >= self.position
		self.write(pad * (aligned_pos - self.position))

class ChunkedStreamReader:
	def __init__(self, stream, size, chunk_size=1 * 1024 * 1024):
		self.stream = stream
		self.size = size
		self.chunk_size = chunk_size

	def for_each_chunk(self, callback):
		remaining_bytes = self.size
		while remaining_bytes > 0:
			copy_len = min(remaining_bytes, self.chunk_size)
			data = self.stream.read(copy_len)
			assert len(data) == copy_len
			callback(data)
			remaining_bytes -= copy_len
			assert remaining_bytes >= 0

@dataclass
class FileDataSource:
	path: str

	def get_chunk(self, offset, size):
		return FileDataChunk(self, offset, size)

	def to_chunk(self):
		size = os.path.getsize(self.path)
		return self.get_chunk(0, size)

class DataChunk:
	def hash_digest(self, algo):
		hash = hashlib.new(algo)
		with self as src:
			chunker = ChunkedStreamReader(src, self.size)
			chunker.for_each_chunk(lambda data: hash.update(data))
		return hash.digest()

@dataclass
class FileDataChunk(DataChunk):
	src: FileDataSource
	offset: int
	size: int

	def __enter__(self):
		stream = open(self.src.path, 'rb')
		try:
			stream.seek(self.offset, os.SEEK_CUR)
		except Exception as e:
			stream.close()
			raise e
		self.stream = stream
		return stream

	def __exit__(self, type, value, traceback):
		self.stream.close()
		self.stream = None

	def copy_to_stream(self, dst):
		with self as src:
			chunker = ChunkedStreamReader(src, self.size)
			chunker.for_each_chunk(lambda data: dst.write(data))

	def __len__(self):
		return self.size

class FwChunk:
	def __init__(self):
		pass

@dataclass
class FwHeader(FwChunk):
	MAGIC = b'AZ01'

	unknown_1: str
	unknown_2: str
	name: str
	compatibles: list
	usb_ids: list
	description: str

	@classmethod
	def from_stream(cls, stream, _):
		unknown_1 = stream.read(4)
		unknown_2 = stream.read(4)
		name = stream.read_str()
		num_compatible = stream.read_u32()
		compatibles = [ ]
		for _ in range(num_compatible):
			compatibles.append(stream.read_str())
		num_usb_ids = stream.read_u32()
		usb_ids = [ ]
		for _ in range(num_usb_ids):
			usb_ids.append(stream.read_u32())
		description = stream.read_str()
		return cls(unknown_1, unknown_2, name, compatibles, usb_ids, description)

	def serialize_to_stream(self, writer):
		writer.write(FwHeader.MAGIC)
		writer.write(self.unknown_1)
		writer.write(self.unknown_2)
		writer.write_str(self.name)
		writer.write_u32(len(self.compatibles))
		for compat in self.compatibles:
			writer.write_str(compat)
		writer.write_u32(len(self.usb_ids))
		for usb_id in self.usb_ids:
			writer.write_u32(usb_id)
		writer.write_str(self.description)
		writer.align()

@dataclass
class FwPartition(FwChunk):
	MAGIC = b'PART'
	subtype: str
	original_size: int
	name: str
	compression_type: str
	unknown_1: int
	hash_type: str
	hash_len: int
	original_hash: str
	aligned_size: int
	data_pos_in_input: int
	data_chunk: DataChunk

	@classmethod
	def from_stream(cls, stream, data_source):
		subtype = stream.read(4)
		size = stream.read_u64()

		name = stream.read_str()
		compression_type = stream.read_str()
		unknown_1 = stream.read_u32() # Number of additional headers maybe?
		hash_type = stream.read_str()

		hash_len = stream.read_u32()
		aligned_len = align_up(hash_len, 4)
		hash = stream.read(aligned_len)

		aligned_size = align_up(size, 4)
		data_pos_in_input = stream.position
		data_chunk = data_source.get_chunk(stream.position, size)
		stream.seek(aligned_size)

		try:
			if data_chunk.hash_digest(hash_type.decode('ascii')) != hash:
				print(f'WARNING: Calculated partition data hash and actual partition data hash do not match')
		except Exception as e:
			print(f'WARNING: Failed to calculate parition data hash, image modifications will probably fail or the resulting image might not work: {e}')

		return cls(subtype, size, name, compression_type, unknown_1, hash_type, hash_len, hash, aligned_size, data_pos_in_input, data_chunk)

	def serialize_to_stream(self, writer):
		writer.write(FwPartition.MAGIC)
		writer.write(self.subtype)
		writer.write_u64(len(self.data_chunk))
		writer.write_str(self.name)
		writer.write_str(self.compression_type)
		writer.write_u32(self.unknown_1)
		writer.write_str(self.hash_type)
		data_hash_digest = self.get_data_digest()
		writer.write_u32(len(data_hash_digest))
		writer.write(data_hash_digest)
		self.data_chunk.copy_to_stream(writer)
		writer.align()

	def get_size(self):
		return len(self.data_chunk)

	def get_data_digest(self):
		return self.data_chunk.hash_digest(self.hash_type.decode('ascii'))

	def dump_to_file(self, path):
		with open(path, 'wb') as f:
			self.data_chunk.copy_to_stream(f)

	def replace_data_chunk(self, data_chunk):
		self.data_chunk = data_chunk

@dataclass
class FwEof(FwChunk):
	MAGIC = b'EOF\x00'

	unknown_1: int
	unknown_2: int

	@classmethod
	def from_stream(cls, stream, _):
		unknown_1 = stream.read(4)
		unknown_2 = stream.read(4)
		return cls(unknown_1, unknown_2)

	def serialize_to_stream(self, writer):
		writer.write(FwEof.MAGIC)
		writer.write(self.unknown_1)
		writer.write(self.unknown_2)
		writer.align()

class FwFile:
	CHUNK_TYPES = {
		FwHeader.MAGIC: FwHeader,
		FwPartition.MAGIC: FwPartition,
		FwEof.MAGIC: FwEof
	}

	@classmethod
	def from_file(cls, path):
		with open(path, 'rb') as f:
			return cls.from_stream(f, FileDataSource(path))

	@classmethod
	def from_stream(cls, stream, data_source):
		reader = BinaryStreamReader(stream)
		chunks = [ ]
		while True:
			reader.align()
			magic = reader.read(4)
			if not magic in FwFile.CHUNK_TYPES:
				raise Exception(f"Unknown chunk type {magic}, can't continue")
			chunk = FwFile.CHUNK_TYPES[magic].from_stream(reader, data_source)
			chunks.append(chunk)
			if isinstance(chunk, FwEof):
				break
		return cls(chunks)

	def __init__(self, chunks):
		self.chunks = chunks

	def write_to_stream(self, stream):
		writer = BinaryStreamWriter(stream)
		for chunk in self.chunks:
			chunk.serialize_to_stream(writer)

	def write_to_file(self, path):
		with open(path, 'wb') as f:
			self.write_to_stream(f)

	def get_partitions(self):
		for chunk in self.chunks:
			if isinstance(chunk, FwPartition):
				yield chunk

	def find_partition(self, filter_fn):
		for chunk in self.chunks:
			if isinstance(chunk, FwPartition) and filter_fn(chunk):
				return chunk
		return None

	def find_partition_by_name(self, name):
		binary_name = name.encode('utf8')
		return self.find_partition(lambda part: part.name == binary_name)

	def find_partition_by_subtype(self, subtype):
		return self.find_partition(lambda part: part.subtype == subtype)

	def get_header(self):
		if self.chunks and isinstance(self.chunks[0], FwHeader):
			return self.chunks[0]

		return None

	def get_footer(self):
		if self.chunks and isinstance(self.chunks[-1], FwEof):
			return self.chunks[-1]

		return None

@click.group()
def cli():
	pass

@cli.command()
@click.argument('infile')
def info(infile):
	fw = FwFile.from_file(infile)
	hdr = fw.get_header()
	if hdr is None:
		print('WARNING: No firmware header found, format incompatible or corrupted')
	else:
		print('==== Header ====')
		print(f' Version:     {hdr.name}')
		print(f' Description: {hdr.description}')
		for compat in hdr.compatibles:
			print(f' Compatible:  {compat}')
		for usb_id in hdr.usb_ids:
			print(f' USB ID:      {usb_id >> 16:04x}:{usb_id & 0xffff:04x}')

	part_idx = 0
	for part in fw.get_partitions():
		print(f'==== Partition {part_idx} ====')
		print(f' Subtype:      {part.subtype}')
		print(f' Name:         {part.name}')
		print(f' Size:         {part.get_size()}')
		print(f' Compression:  {part.compression_type}')
		print(f' Hash algo:    {part.hash_type}')
		print(f' Hash digest:  {part.get_data_digest().hex()}')
		part_idx += 1
	footer = fw.get_footer()
	if footer is None:
		print('WARNING: No firmware EOF marker found, format incompatible or corrupted')

@cli.command()
@click.argument('infile')
@click.argument('outfile')
def copy(infile, outfile):
	FwFile.from_file(infile).write_to_file(outfile)

@cli.command()
@click.argument('infile')
@click.argument('outfile')
def extract_rootfs(infile, outfile):
	fw = FwFile.from_file(infile)
	root_part = fw.find_partition_by_name('rootfs')
	if root_part is None:
		print('WARNING: Did not find rootfs partition by name, trying to match subtype...')
		root_part = fw.find_partition_by_subtype(b'L\x00\x00\x00')
	if root_part is None:
		print('Failed to find rootfs partition')
		return
	root_part.dump_to_file(outfile)

@cli.command()
@click.argument('infile')
@click.argument('outfile')
@click.argument('rootfs_file')
def replace_rootfs(infile, outfile, rootfs_file):
	fw = FwFile.from_file(infile)
	root_part = fw.find_partition_by_name('rootfs')
	if root_part is None:
		print('WARNING: Did not find root partition by name, trying to match subtype...')
		root_part = fw.find_partition_by_subtype(b'L\x00\x00\x00')
	if root_part is None:
		print('Failed to find rootfs partition')
		return
	data_source = FileDataSource(rootfs_file)
	root_part.replace_data_chunk(data_source.to_chunk())
	fw.write_to_file(outfile)

if __name__ == '__main__':
	cli()

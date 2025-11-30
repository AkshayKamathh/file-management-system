#!/usr/bin/env python3

import os
import json
import math

DISK_FILE = "virtual_disk.bin"
META_FILE = "metadata.json"

DISK_SIZE = 1024 * 1024  # 1 MB virtual disk
BLOCK_SIZE = 512         # bytes per block
NUM_BLOCKS = DISK_SIZE // BLOCK_SIZE


class FileSystem:
    def __init__(self):
        # directory: filename -> {size, capacity, first_block}
        self.directory = {}
        # free_map[i] = True means block i is free
        self.free_map = [True] * NUM_BLOCKS
        # fat[i] = index of next block in chain, -1 = end of file, -2 = free
        self.fat = [-2] * NUM_BLOCKS
        # open_file_table: filename -> {"pos": current read/write position}
        self.open_file_table = {}
        self._disk = None  # file handle for virtual_disk.bin

    # ----------------- Initialization & Metadata -----------------

    def init_fileSystem(self):
        """
        Initialize the file system.

        If disk/metadata exist, load them.
        Otherwise, create a fresh disk and empty metadata.
        """
        if os.path.exists(DISK_FILE) and os.path.exists(META_FILE):
            self._load_metadata()
            self._disk = open(DISK_FILE, "r+b")
        else:
            # Create/overwrite disk file
            with open(DISK_FILE, "wb") as f:
                f.truncate(DISK_SIZE)

            # Fresh metadata
            self.directory = {}
            self.free_map = [True] * NUM_BLOCKS
            self.fat = [-2] * NUM_BLOCKS  # -2 = free, -1 = EOF
            self.open_file_table = {}

            self._save_metadata()
            self._disk = open(DISK_FILE, "r+b")

        print("File system initialized.")

    def _save_metadata(self):
        meta = {
            "block_size": BLOCK_SIZE,
            "num_blocks": NUM_BLOCKS,
            "directory": self.directory,
            "free_map": self.free_map,
            "fat": self.fat,
        }
        with open(META_FILE, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    def _load_metadata(self):
        with open(META_FILE, "r", encoding="utf-8") as f:
            meta = json.load(f)

        # simple sanity checks
        if meta.get("block_size") != BLOCK_SIZE or meta.get("num_blocks") != NUM_BLOCKS:
            raise ValueError("Metadata does not match current file system configuration.")

        self.directory = meta.get("directory", {})
        self.free_map = meta.get("free_map", [True] * NUM_BLOCKS)
        self.fat = meta.get("fat", [-2] * NUM_BLOCKS)

    # ----------------- Low-level Block Helpers -----------------

    def _allocate_blocks(self, num_blocks):
        """
        Find num_blocks free blocks and allocate them.
        Returns a list of block indices or None if not enough space.
        """
        free_indices = [i for i, free in enumerate(self.free_map) if free]
        if len(free_indices) < num_blocks:
            return None

        allocated = free_indices[:num_blocks]
        for idx in allocated:
            self.free_map[idx] = False
            self.fat[idx] = -1  # temporarily mark as EOF; we'll chain below

        # Link allocated blocks in a chain
        for i in range(len(allocated) - 1):
            self.fat[allocated[i]] = allocated[i + 1]
        self.fat[allocated[-1]] = -1

        return allocated

    def _free_blocks_chain(self, first_block):
        """
        Free a chain of blocks starting from first_block using the FAT.
        """
        b = first_block
        while b != -1 and b != -2:
            next_b = self.fat[b]
            self.free_map[b] = True
            self.fat[b] = -2  # mark free
            b = next_b

    def _write_block(self, block_index, data_bytes):
        """
        Write up to BLOCK_SIZE bytes into the given block index.
        Pads with zeros if data_bytes < BLOCK_SIZE.
        """
        if len(data_bytes) > BLOCK_SIZE:
            raise ValueError("Trying to write more than BLOCK_SIZE bytes to a block")

        offset = block_index * BLOCK_SIZE
        self._disk.seek(offset)
        to_write = data_bytes + b"\x00" * (BLOCK_SIZE - len(data_bytes))
        self._disk.write(to_write)

    def _read_block(self, block_index):
        """
        Read BLOCK_SIZE bytes from the given block index.
        """
        offset = block_index * BLOCK_SIZE
        self._disk.seek(offset)
        return self._disk.read(BLOCK_SIZE)

    def _get_block_chain(self, first_block):
        """
        Follow FAT starting at first_block and return list of block indices.
        """
        blocks = []
        b = first_block
        while b != -1 and b != -2:
            blocks.append(b)
            b = self.fat[b]
        return blocks

    # ----------------- File Operations -----------------

    def create_file(self, fileName, size_bytes):
        """
        Create a new file with reserved capacity size_bytes.
        Used bytes start at 0; capacity is the max bytes we allow.
        """
        if fileName in self.directory:
            print(f"Error: file '{fileName}' already exists.")
            return

        if size_bytes <= 0:
            print("Error: size must be positive.")
            return

        blocks_needed = math.ceil(size_bytes / BLOCK_SIZE)
        allocated = self._allocate_blocks(blocks_needed)
        if allocated is None:
            print("Error: not enough space on disk to create this file.")
            return

        first_block = allocated[0]
        self.directory[fileName] = {
            "size": 0,              # bytes actually written
            "capacity": size_bytes, # maximum bytes allowed
            "first_block": first_block,
        }
        self._save_metadata()
        print(f"File '{fileName}' created with capacity {size_bytes} bytes.")

    def delete_file(self, fileName):
        """
        Delete a file: free all its blocks and remove from directory and open table.
        """
        entry = self.directory.get(fileName)
        if entry is None:
            print(f"Error: file '{fileName}' not found.")
            return

        self._free_blocks_chain(entry["first_block"])
        self.directory.pop(fileName, None)
        self.open_file_table.pop(fileName, None)
        self._save_metadata()
        print(f"File '{fileName}' deleted.")

    def open_file(self, fileName):
        """
        Logical open: check that file exists and add to open file table.
        """
        if fileName not in self.directory:
            print(f"Error: file '{fileName}' not found.")
            return

        if fileName in self.open_file_table:
            print(f"File '{fileName}' is already open.")
            return

        self.open_file_table[fileName] = {"pos": 0}
        print(f"File '{fileName}' opened.")

    def close_file(self, fileName):
        """
        Logical close: remove from open file table.
        """
        if fileName not in self.open_file_table:
            print(f"Error: file '{fileName}' is not open.")
            return

        self.open_file_table.pop(fileName)
        print(f"File '{fileName}' closed.")

    def write_file(self, fileName, data):
        """
        Overwrite the file from the beginning with the given data string.
        Does not change capacity; if data is larger than capacity, prints an error.
        """
        if fileName not in self.directory:
            print(f"Error: file '{fileName}' not found.")
            return

        if fileName not in self.open_file_table:
            print(f"Error: file '{fileName}' is not open.")
            return

        entry = self.directory[fileName]
        data_bytes = data.encode("utf-8")

        if len(data_bytes) > entry["capacity"]:
            print("Error: data is larger than file capacity.")
            return

        blocks = self._get_block_chain(entry["first_block"])

        remaining = len(data_bytes)
        offset = 0
        for b in blocks:
            if remaining <= 0:
                # If we wrote fewer bytes than capacity, zero out rest of block
                self._write_block(b, b"")
                continue
            chunk = data_bytes[offset:offset + BLOCK_SIZE]
            self._write_block(b, chunk)
            written = len(chunk)
            remaining -= written
            offset += written

        entry["size"] = len(data_bytes)
        self.open_file_table[fileName]["pos"] = len(data_bytes)
        self._save_metadata()
        print(f"Wrote {len(data_bytes)} bytes to '{fileName}'.")

    def read_file(self, fileName, length=None):
        """
        Read 'length' bytes from the beginning of the file.
        If length is None or larger than file size, read the whole file.
        """
        if fileName not in self.directory:
            print(f"Error: file '{fileName}' not found.")
            return

        if fileName not in self.open_file_table:
            print(f"Error: file '{fileName}' is not open.")
            return

        entry = self.directory[fileName]
        file_size = entry["size"]

        if file_size == 0:
            print(f"File '{fileName}' is empty.")
            return ""

        if length is None or length > file_size:
            length = file_size

        blocks = self._get_block_chain(entry["first_block"])
        remaining = length
        data_bytes = b""

        for b in blocks:
            if remaining <= 0:
                break
            block_data = self._read_block(b)
            chunk = block_data[:min(remaining, BLOCK_SIZE)]
            data_bytes += chunk
            remaining -= len(chunk)

        result = data_bytes.decode("utf-8", errors="ignore")
        print(f"Contents of '{fileName}':")
        print(result)
        return result

    def list_files(self):
        """
        List all files in the directory table.
        """
        if not self.directory:
            print("No files in file system.")
            return

        print("Files:")
        for name, entry in self.directory.items():
            print(f"- {name}: size={entry['size']} bytes, capacity={entry['capacity']} bytes")

    def search_file(self, keyword):
        """
        Search for files whose names contain the given keyword.
        """
        matches = [name for name in self.directory if keyword in name]
        if not matches:
            print(f"No files found containing '{keyword}'.")
            return

        print(f"Files containing '{keyword}':")
        for name in matches:
            print(f"- {name}")


def main():
    fs = FileSystem()
    fs.init_fileSystem()
    print("Simple File Management System on virtual_disk.bin")
    print("Commands: create, open, close, write, read, delete, ls, search, exit")

    while True:
        try:
            cmd = input("fs> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not cmd:
            continue

        parts = cmd.split()
        command = parts[0].lower()

        if command == "create" and len(parts) == 3:
            name = parts[1]
            try:
                size = int(parts[2])
            except ValueError:
                print("Size must be an integer (bytes).")
                continue
            fs.create_file(name, size)

        elif command == "open" and len(parts) == 2:
            fs.open_file(parts[1])

        elif command == "close" and len(parts) == 2:
            fs.close_file(parts[1])

        elif command == "write" and len(parts) >= 3:
            # everything after filename is data, optionally quoted
            name = parts[1]
            rest = cmd[cmd.index(name) + len(name):].strip()
            if rest.startswith('"') and rest.endswith('"'):
                data = rest[1:-1]
            else:
                data = rest
            fs.write_file(name, data)

        elif command == "read":
            if len(parts) < 2:
                print("Usage: read <fileName> [length]")
                continue
            name = parts[1]
            length = None
            if len(parts) == 3:
                try:
                    length = int(parts[2])
                except ValueError:
                    print("Length must be an integer.")
                    continue
            fs.read_file(name, length)

        elif command == "delete" and len(parts) == 2:
            fs.delete_file(parts[1])

        elif command == "ls":
            fs.list_files()

        elif command == "search" and len(parts) == 2:
            fs.search_file(parts[1])

        elif command == "exit":
            print("Goodbye.")
            break

        else:
            print("Unknown command or wrong usage.")


if __name__ == "__main__":
    main()

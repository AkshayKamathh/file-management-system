RAM-Disk File Management System

A small FAT-style file system simulator that uses a 1MB RAM disk to store file contents in 512-byte blocks.
Supports basic directory and file operations with persistence via metadata + disk snapshot.

Features

Directory operations: mkdir, cd, ls, delete (only empty dirs)

File operations: create, open, write, read, close, delete

Move/rename: mv

Global search by name: search

Uses a RAM bytearray to simulate disk storage

Persists state using:

metadata.json (directory tree, FAT, free map)

virtual_disk.bin (RAM snapshot)

Requirements

Python 3.x

How to Run
cd file-management-system
python3 file_system.py

Commands

Inside the program:

mkdir <dir>
cd <dir | .. | />
ls
create <file>
open <file>
write <file> "your text here"
read <file>
close <file>
mv <src> <dest>
search <name>
delete <file | empty_dir>
exit

Quick Demo Script
mkdir docs
ls
cd docs
ls
cd /

create notes.txt
open notes.txt
write notes.txt "hey from the terminal!"
close notes.txt

open notes.txt
read notes.txt

search notes.txt
mv notes.txt ideas.txt
search ideas.txt

delete ideas.txt
delete docs
exit

Reset the File System

To start fresh:

rm -f metadata.json virtual_disk.bin

EPUB to MP3
===========

Turns an EPUB book into MP3 audiobook files, entirely on your own computer.
Nothing is uploaded anywhere. No Python, no command line, no accounts.


FIRST RUN
---------
The first time you open the program it downloads the voice model - two files,
about 330 MB in total - and stores them in your user folder. That needs an
internet connection and takes a few minutes. Everything after that works
completely offline, including on a machine that has never been online since.


USING IT
--------
1. Click "Choose..." next to EPUB file and pick your book.
   The chapter list fills in with an estimate of how long each one will be.

2. Untick any chapters you do not want (the front matter, for example).

3. Pick a voice. "Preview" reads a sample sentence so you can hear it before
   committing to a ten-hour book.

4. Adjust the speed if you like. 1.0x is the natural pace; many audiobook
   listeners prefer 1.1x to 1.25x.

5. Click "Convert to MP3".

You get one MP3 per chapter, numbered so they play in order, tagged with the
book title and author so audiobook apps group them correctly.


HOW LONG DOES IT TAKE
---------------------
Roughly one to three times faster than real time on a typical laptop, and it
scales with the number of processor cores. A ten-hour book is usually a three
to eight hour job. You can stop at any point: finished chapters are kept, and
if you restart later with "Skip chapters already converted" ticked, it picks up
where it left off.

The window stays responsive throughout - you can keep using your computer.


IF SOMETHING GOES WRONG
-----------------------
Windows SmartScreen warning on first launch
    Expected. The program is not code-signed (a certificate costs a few hundred
    dollars a year). Click "More info" then "Run anyway".

"The speech engine could not start"
    Usually a partially downloaded model. Delete the folder
    %LOCALAPPDATA%\EpubToMP3\models and restart the program to download again.

Antivirus quarantines the program
    PyInstaller-built executables trip heuristic scanners fairly often. Add an
    exclusion for the install folder, or build it yourself from the source in
    this folder so it is your own binary.

Chapters are missing or in a strange order
    Some EPUBs have an unusual internal structure. Very short sections (under
    200 characters) are skipped on purpose, since they are almost always cover
    pages or copyright notices.

Nothing happens when you click Convert
    Look at the message line at the bottom of the window, and at the log box
    underneath it. If the program crashed at startup, details are written to
    %LOCALAPPDATA%\EpubToMP3\error.log

Troubleshooting from a command prompt
    EpubToMP3-cli.exe sits next to the main program and prints errors in full:
        EpubToMP3-cli.exe "C:\books\mybook.epub" -o "C:\out" --voice af_heart
        EpubToMP3-cli.exe --list-voices
        EpubToMP3-cli.exe "C:\books\mybook.epub" --list-chapters


MOVING IT TO A COMPUTER WITH NO INTERNET
----------------------------------------
Install it on a connected machine, run it once so the model downloads, then
copy %LOCALAPPDATA%\EpubToMP3\models to the same place on the offline machine.
Alternatively, put the two model files in a folder called "models" next to
EpubToMP3.exe and the program will find them there.


LICENSING
---------
See LICENSE.txt. Short version: the app code is MIT, but the finished
executable bundles espeak-ng and phonemizer, which are GPL v3 - so if you pass
the program on to other people, pass the source folder on with it.

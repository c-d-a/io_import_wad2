# Blender WAD2 Importer

This addon creates materials for imported images and marks them as assets.
Despite the name, it can also import loose images and textures from .bsp files.

Supported Blender versions: 2.83 - 3.3+

All created materials will get marked as assets and tagged by input .wad or folder. Special materials such as water, sky, and animated texture sequences will get additional node groups set up. The addon can also be configured to name materials using a relative path instead of just the texture name.


## Installation
Download [io_import_wad2.py](https://github.com/c-d-a/io_import_wad2/raw/master/io_import_wad2.py), then select it under "Edit > Preferences > Add-ons > Install".  
The addon preferences allow you to change the base path for relative texture naming, and the suffix for glow texture detection.


## Extra Features
The addon includes some useful functionality not strictly related to .wad files.

### Importing Loose Images
To be able to import separate texture files, you'll want to disable the extension filter at the top of the import dialog. Then select the individual files and import. This will create the same basic materials as with .wad files, meaning diffuse and emission only. For anything more complex, you'll probably want to use some other addon.

### Reset Texel Density
This operator resets texel density of selected faces to 1 texel/unit (by default). It can be found in the 3D view's UV section. Unlike similar functionality in existing plugins, this one will automatically detect the image sizes. Optionally, the operator can cube-project UVs before resetting the density. The operation will not attempt to aspect-correct your unwrap, so unless you cube-project, you'll want to account for that beforehand.

### Apply Asset to Selection
As of Blender 3.3.0, the asset drag'n'drop operation is restricted to object mode or material slots. This new operator aims to lift this restriction. You can find the operator in the Asset Browser's right-click context menu. Hopefully, this functionality will eventually become a built-in part of Blender, but for now this will have to do.

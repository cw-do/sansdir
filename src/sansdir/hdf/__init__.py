"""HDF5 / NeXus support — reader, metadata extractor, batch tools.

Imports stay lazy: nothing in this module's ``__init__`` pulls in
``h5py``. Callers ``from sansdir.hdf.reader import ...`` at the call
site to keep the cold-start budget intact.
"""

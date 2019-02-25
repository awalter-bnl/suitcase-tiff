# Suitcase subpackages must follow strict naming and interface conventions. The
# public API should include some subset of the following. Any functions not
# implemented should be omitted, rather than included and made to raise
# NotImplementError, so that a client importing this library can immediately
# know which portions of the suitcase API it supports without calling any
# functions.
from suitcase import tiff_series
from tifffile import TiffWriter
import event_model
import numpy
from ._version import get_versions

__version__ = get_versions()['version']
del get_versions


def export(gen, directory, file_prefix='{uid}-', bigtiff=False, byteorder=None,
           imagej=False, **kwargs):
    """
    Export a stream of documents to TIFF stack(s).

    This creates a file named:
    ``<directory>/<file_prefix>{stream_name}-{field}.tiff``
    for every Event stream and field that contains 2D 'image like' data.

    .. warning::

        This process explicitly ignores all data that is not 2D and does not
        include any metadata in the output file.

    .. note::

        This can alternatively be used to write data to generic buffers rather
        than creating files on disk. See the documentation for the
        ``directory`` parameter below.

    Parameters
    ----------
    gen : generator
        expected to yield ``(name, document)`` pairs

    directory : string, Path or Manager.
        For basic uses, this should be the path to the output directory given
        as a string or Path object. Use an empty string ``''`` to place files
        in the current working directory.

        In advanced applications, this may direct the serialized output to a
        memory buffer, network socket, or other writable buffer. It should be
        an instance of ``suitcase.utils.MemoryBufferManager`` and
        ``suitcase.utils.MultiFileManager`` or any object implementing that
        inferface. See the suitcase documentation (LINK ONCE WRITTEN) for
        details.

    file_prefix : str, optional
        The first part of the filename of the generated output files. This
        string may include templates as in ``{proposal_id}-{sample_name}-``,
        which are populated from the RunStart document. The default value is
        ``{uid}-`` which is guaranteed to be present and unique. A more
        descriptive value depends on the application and is therefore left to
        the user.

    bigtiff : boolean, optional
        Passed into ``tifffile.TiffWriter``. Default False.

    byteorder : string or None, optional
        Passed into ``tifffile.TiffWriter``. Default None.

    imagej: boolean, optional
        Passed into ``tifffile.TiffWriter``. Default False.

    **kwargs : kwargs
        kwargs to be passed to ``tifffile.TiffWriter.save``.

    Returns
    -------
    dest : dict
        dict mapping the 'labels' to lists of file names

    Examples
    --------

    Generate files with unique-identifer names in the current directory.

    >>> export(gen, '')

    Generate files with more readable metadata in the file names.

    >>> export(gen, '', '{plan_name}-{motors}-')

    Include the experiment's start time formatted as YY-MM-DD_HH-MM.

    >>> export(gen, '', '{time:%%Y-%%m-%%d_%%H:%%M}-')

    Place the files in a different directory, such as on a mounted USB stick.

    >>> export(gen, '/path/to/my_usb_stick')
    """
    with Serializer(directory, file_prefix,
                    bigtiff=bigtiff,
                    byteorder=byteorder,
                    imagej=imagej,
                    **kwargs) as serializer:
        for item in gen:
            serializer(*item)

    return serializer.artifacts


# NOTE: Below I have made this a child of suitcase-tiff/suitcase/tiff_series to
# reduce the amount of duplicate code.


class Serializer(tiff_series.Serializer):
    """
    Serialize a stream of documents to TIFF stack(s).

    This creates a file named:
    ``<directory>/<file_prefix>{stream_name}-{field}.tiff``
    for every Event stream and field that contains 2D 'image like' data.

    .. warning::

        This process explicitly ignores all data that is not 2D and does not
        include any metadata in the output file.


    .. note::

        This can alternatively be used to write data to generic buffers rather
        than creating files on disk. See the documentation for the
        ``directory`` parameter below.

    Parameters
    ----------
    directory : string, Path or Manager.
        For basic uses, this should be the path to the output directory given
        as a string or Path object. Use an empty string ``''`` to place files
        in the current working directory.

        In advanced applications, this may direct the serialized output to a
        memory buffer, network socket, or other writable buffer. It should be
        an instance of ``suitcase.utils.MemoryBufferManager`` and
        ``suitcase.utils.MultiFileManager`` or any object implementing that
        inferface. See the suitcase documentation (LINK ONCE WRITTEN) for
        details.

    file_prefix : str, optional
        The first part of the filename of the generated output files. This
        string may include templates as in ``{proposal_id}-{sample_name}-``,
        which are populated from the RunStart document. The default value is
        ``{uid}-`` which is guaranteed to be present and unique. A more
        descriptive value depends on the application and is therefore left to
        the user.

    stack_images : Boolean
        This indicates if we want one image per file (`stack_images` = `False`)
        or many images per file (`stack_images` = `True`). If using
        `stack_images` = `False` then an additional image number is added to
        the file name.

    bigtiff : boolean, optional
        Passed into ``tifffile.TiffWriter``. Default False.

    byteorder : string or None, optional
        Passed into ``tifffile.TiffWriter``. Default None.

    imagej: boolean, optional
        Passed into ``tifffile.TiffWriter``. Default False.

    **kwargs : kwargs
        kwargs to be passed to ``tifffile.TiffWriter.save``.
    """

    def start(self, doc):
        '''Extracts `start` document information for formatting file_prefix.

        This method checks that only one `start` document is seen and formats
        `file_prefix` based on the contents of the `start` document.

        Parameters:
        -----------
        doc : dict
            RunStart document
        '''

        # format self._file_prefix using only the start document
        self._templated_file_prefix = self._file_prefix.format(**doc)
        # run the rest of the parents start function.
        super().start(doc)

    def event_page(self, doc):
        '''Add event page document information to a ".tiff" file.

        This method adds event_page document information to a ".tiff" file,
        creating it if nesecary.

        .. warning::

            All non 2D 'image like' data is explicitly ignored.

        .. note::

            The data in Events might be structured as an Event, an EventPage,
            or a "bulk event" (deprecated). The DocumentRouter base class takes
            care of first transforming the other repsentations into an
            EventPage and then routing them through here, so no further action
            is required in this class. We can assume we will always receive an
            EventPage.

        Parameters:
        -----------
        doc : dict
            EventPage document
        '''
        event_model.verify_filled(doc)
        streamname = self._descriptors[doc['descriptor']].get('name')
        for field in doc['data']:
            for img in doc['data'][field]:
                # check that the data is 2D, if not ignore it
                img_asarray = numpy.asarray(img)
                if img_asarray.ndim == 2:
                    # create a file for this stream and field if required
                    if not self._tiff_writers.get(streamname, {}).get(field):
                        filename = (f'{self._templated_file_prefix}'
                                    f'{streamname}-{field}.tiff')
                        file = self._manager.open(
                            'stream_data', filename, 'xb')
                        tw = TiffWriter(file, **self._init_kwargs)
                        self._tiff_writers[streamname][field] = tw
                    # append the image to the file
                    tw = self._tiff_writers[streamname][field]
                    tw.save(img_asarray, *self._kwargs)

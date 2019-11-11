# emacs: -*- mode: python; py-indent-offset: 4; tab-width: 4; indent-tabs-mode: nil -*-
# ex: set sts=4 ts=4 sw=4 noet:
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the datalad package for the
#   copyright and license terms.
#
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
"""Report status of a dataset (hierarchy)'s work tree"""

__docformat__ = 'restructuredtext'


import logging
import os
import os.path as op
from hashlib import md5
import subprocess
from argparse import REMAINDER

from datalad.utils import (
    rmtree,
)
from datalad.interface.base import (
    Interface,
    build_doc,
)
from datalad.interface.results import (
    get_status_dict,
)
from datalad.interface.utils import eval_results
from datalad.support.param import Parameter
from datalad.support.constraints import (
    EnsureNone,
    EnsureStr,
)
from datalad.distribution.dataset import (
    EnsureDataset,
    datasetmethod,
    require_dataset,
    resolve_path,
)
from datalad.log import log_progress
from datalad.dochelpers import (
    exc_str,
)

lgr = logging.getLogger('ria_remote.export_archive')


@build_doc
class ExportArchive(Interface):
    """Export an archive of a local annex object store for the RIA remote.
    """
    # make the custom renderer the default one, as the global default renderer
    # does not yield meaningful output for this command
    _params_ = dict(
        dataset=Parameter(
            args=("-d", "--dataset"),
            doc="""specify the dataset to process.  If
            no dataset is given, an attempt is made to identify the dataset
            based on the current working directory""",
            constraints=EnsureDataset() | EnsureNone()),
        outputdir=Parameter(
            args=("outputdir",),
            metavar="DIRECTORY",
            doc="""directory to place the archive into""",
            constraints=EnsureStr() | EnsureNone()),
        opts=Parameter(
            args=("opts",),
            nargs=REMAINDER,
            metavar="OPTIONS",
            doc="""additional options for 7z"""),
    )

    @staticmethod
    @datasetmethod(name='ria_export_archive')
    @eval_results
    def __call__(
            outputdir,
            dataset=None,
            opts=None):
        # only non-bare repos have hashdirmixed, so require one
        ds = require_dataset(
            dataset, check_installed=True, purpose='RIA archive export')
        ds_repo = ds.repo
        annex_objs = ds_repo.dot_git / 'annex' / 'objects'

        archive = resolve_path(outputdir, dataset)
        if archive.is_dir():
            archive = archive / 'archive.7z'

        if not opts:
            opts = ['-mx0']

        res_kwargs = dict(
            action="export-ria-archive",
            logger=lgr,
        )

        if not annex_objs.is_dir():
            yield get_status_dict(
                ds=ds,
                status='notneeded',
                message='no annex keys present',
                **res_kwargs,
            )
            return

        exportdir = ds_repo.dot_git / 'datalad' / 'tmp' / 'ria_archive'
        if exportdir.exists():
            yield get_status_dict(
                ds=ds,
                status='error',
                message=(
                    'export directory already exists, please remove first: %s',
                    str(exportdir)),
                **res_kwargs,
            )
            return

        keypaths = [
            k for k in annex_objs.glob(op.join('**', '*'))
            if k.is_file()
        ]

        log_progress(
            lgr.info,
            'riaarchiveexport',
            'Start RIA archive export %s', ds,
            total=len(keypaths),
            label='RIA archive export',
            unit=' Keys',
        )

        for keypath in keypaths:
            key = keypath.name
            md5sum = md5(key.encode()).hexdigest()
            hashdir = op.join(md5sum[:3], md5sum[3:6])
            log_progress(
                lgr.info,
                'riaarchiveexport',
                'Export key %s to %s', key, hashdir,
                update=1,
                increment=True)
            keydir = exportdir / hashdir / key
            keydir.mkdir(parents=True, exist_ok=True)
            os.link(keypath, str(keydir / key))

        log_progress(
            lgr.info,
            'riaarchiveexport',
            'Finished RIA archive export from %s', ds
        )
        try:
            subprocess.run(
                ['7z', 'u', str(archive), '.'] + opts,
                cwd=str(exportdir),
            )
            yield get_status_dict(
                path=str(archive),
                type='file',
                status='ok',
                **res_kwargs)
        except Exception as e:
            yield get_status_dict(
                path=str(archive),
                type='file',
                status='error',
                message=('7z failed: %s', exc_str(e)),
                **res_kwargs)
            return
        finally:
            rmtree(str(exportdir))

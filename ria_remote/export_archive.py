# emacs: -*- mode: python; py-indent-offset: 4; tab-width: 4; indent-tabs-mode: nil -*-
# ex: set sts=4 ts=4 sw=4 noet:
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
#
#   See COPYING file distributed along with the datalad package for the
#   copyright and license terms.
#
# ## ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ### ##
"""Export an archive of a local annex object store, suitable for RIA"""

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

    Keys in the local annex object store are reorganized in a temporary
    directory (using links to avoid storage duplication) to use the
    'hashdirlower' setup used by git-annex for bare repositories and
    the directory-type special remote. This alternative object store is
    then moved into a 7zip archive that is suitable for use in a
    RIA remote dataset store. Placing such an archive into::

      <dataset location>/archives/archive.7z

    Enables the RIA special remote to locate and retrieve all key contained
    in the archive.
    """
    _params_ = dict(
        dataset=Parameter(
            args=("-d", "--dataset"),
            doc="""specify the dataset to process.  If
            no dataset is given, an attempt is made to identify the dataset
            based on the current working directory""",
            constraints=EnsureDataset() | EnsureNone()),
        target=Parameter(
            args=("target",),
            metavar="TARGET",
            doc="""if an existing directory, an 'archive.7z' is placed into
            it, otherwise this is the path to the target archive""",
            constraints=EnsureStr() | EnsureNone()),
        opts=Parameter(
            args=("opts",),
            nargs=REMAINDER,
            metavar="...",
            doc="""list of options for 7z to replace the default '-mx0' to
            generate an uncompressed archive"""),
    )

    @staticmethod
    @datasetmethod(name='ria_export_archive')
    @eval_results
    def __call__(
            target,
            dataset=None,
            opts=None):
        # only non-bare repos have hashdirmixed, so require one
        ds = require_dataset(
            dataset, check_installed=True, purpose='RIA archive export')
        ds_repo = ds.repo

        # TODO remove once datalad 0.12rc7 or later is released
        from datalad.support.gitrepo import GitRepo
        ds_repo.dot_git = ds_repo.pathobj / GitRepo.get_git_dir(ds_repo)

        annex_objs = ds_repo.dot_git / 'annex' / 'objects'

        archive = resolve_path(target, dataset)
        if archive.is_dir():
            archive = archive / 'archive.7z'
        else:
            archive.parent.mkdir(exist_ok=True, parents=True)

        if not opts:
            # uncompressed by default
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
            os.link(str(keypath), str(keydir / key))

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

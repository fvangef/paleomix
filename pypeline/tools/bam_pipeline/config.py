#!/usr/bin/python
#
# Copyright (c) 2013 Mikkel Schubert <MSchubert@snm.ku.dk>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
#
import os
import optparse

import pypeline

from pypeline.config import \
     ConfigError, \
     PerHostValue, \
     PerHostConfig




def _run_config_parser(argv):
    per_host_cfg = PerHostConfig("bam_pipeline")

    usage_str    = "%prog <command> [options] [makefiles]"
    version_str  = "%%prog %s" % (pypeline.__version__,)
    parser       = optparse.OptionParser(usage = usage_str, version = version_str)
    parser.add_option("--allow-missing-input-files", action = "store_true", default = False,
                      help = "Allow processing of lanes, even if the original input files are no-longer " \
                             "accesible, if for example a network drive is down. This option should be " \
                             "used with care!")

    pypeline.ui.add_optiongroup(parser, default = PerHostValue("quiet"))
    pypeline.logger.add_optiongroup(parser)

    group  = optparse.OptionGroup(parser, "Scheduling")
    group.add_option("--bowtie2-max-threads", type = int, default = PerHostValue(4),
                     help = "Maximum number of threads to use per BWA instance [%default]")
    group.add_option("--bwa-max-threads", type = int, default = PerHostValue(4),
                     help = "Maximum number of threads to use per BWA instance [%default]")
    group.add_option("--max-threads", type = int, default = per_host_cfg.max_threads,
                     help = "Maximum number of threads to use in total [%default]")
    group.add_option("--dry-run", action = "store_true", default = False,
                     help = "If passed, only a dry-run in performed, the dependency "
                            "tree is printed, and no tasks are executed.")
    parser.add_option_group(group)

    group  = optparse.OptionGroup(parser, "Required paths")
    group.add_option("--jar-root", default = PerHostValue("~/install/jar_root", is_path = True),
                     help = "Folder containing Picard JARs (http://picard.sf.net), " \
                            "and GATK (www.broadinstitute.org/gatk). " \
                            "The latter is only required if realigning is enabled. " \
                            "[%default]")
    group.add_option("--temp-root", default = per_host_cfg.temp_root,
                     help = "Location for temporary files and folders [%default/]")
    group.add_option("--destination", default = None,
                     help = "The destination folder for result files. By default, files will be "
                            "placed in the same folder as the makefile which generated it.")
    parser.add_option_group(group)

    group  = optparse.OptionGroup(parser, "Output files and orphan files")
    group.add_option("--list-output-files", action = "store_true", default = False,
                     help = "List all files generated by pipeline for the makefile(s).")
    group.add_option("--list-orphan-files", action = "store_true", default = False,
                     help = "List all files at destination not generated by the pipeline. " \
                            "Useful for cleaning up after making changes to a makefile.")
    parser.add_option_group(group)

    group  = optparse.OptionGroup(parser, "Targets")
    group.add_option("--target", dest = "targets", action = "append", default = [],
                     help = "Only execute nodes required to build specified target.")
    group.add_option("--list-targets", default = None,
                     help = "List all targets at a given resolution (target, sample, library, lane, reads)")
    parser.add_option_group(group)

    return per_host_cfg.parse_args(parser, argv)


def parse_config(argv):
    config, args = _run_config_parser(argv)

    config.targets = set(config.targets)
    targets_by_name = ("targets", "prefixes", "samples", "libraries", "lanes", "mapping", "trimming")
    if (config.list_targets is not None) and (config.list_targets not in targets_by_name):
        raise ConfigError("ERROR: Invalid value for --list-targets (%s), valid values are '%s'." \
                          % (repr(config.list_targets), "', '".join(targets_by_name)))

    if config.list_output_files and config.list_orphan_files:
        raise ConfigError("ERROR: Both --list-output-files and --list-orphan-files set!")

    if not os.path.exists(config.temp_root):
        try:
            os.makedirs(config.temp_root)
        except OSError, e:
            raise ConfigError("ERROR: Could not create temp root:\n\t%s" % (e,))

    if not os.access(config.temp_root, os.R_OK | os.W_OK | os.X_OK):
        raise ConfigError("ERROR: Insufficient permissions for temp root: '%s'" % (config.temp_root,))

    if not args:
        raise ConfigError("Please specify at least one makefile!")

    return config, args


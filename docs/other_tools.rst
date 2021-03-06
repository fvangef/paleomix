.. _other_tools:

Other tools
===========

On top of the pipelines described in the major sections of the documentation, the pipeline comes bundled with several other, smaller tools, all accessible via the 'paleomix' command. These tools are (briefly) described in this section.


paleomix cleanup
----------------

.. TODO:
..    paleomix cleanup          -- Reads SAM file from STDIN, and outputs sorted,
..                                 tagged, and filter BAM, for which NM and MD
                                 tags have been updated.

paleomix coverage
-----------------

.. TODO:
..    paleomix coverage         -- Calculate coverage across reference sequences
..                                 or regions of interest.

paleomix depths
---------------

.. TODO:
..    paleomix depths           -- Calculate depth histograms across reference
..                                 sequences or regions of interest.

paleomix duphist
----------------

.. TODO:
..    paleomix duphist          -- Generates PCR duplicate histogram; used with
..                                 the 'Preseq' tool.

paleomix rmdup_collapsed
------------------------

.. TODO:
..    paleomix rmdup_collapsed  -- Filters PCR duplicates for collapsed paired-
..                                 ended reads generated by the AdapterRemoval
                                 tool.

paleomix genotype
-----------------

.. TODO:
..    paleomix genotype         -- Creates bgzipped VCF for a set of (sparse) BED
..                                 regions, or for entire chromosomes / contigs
..                                 using SAMTools / BCFTools.

paleomix gtf_to_bed
-------------------

.. TODO:
..    paleomix gtf_to_bed       -- Convert GTF file to BED files grouped by
..                                 feature (coding, RNA, etc).


paleomix sample_pileup
----------------------

.. TODO:
..    paleomix sample_pileup    -- Randomly sample sites in a pileup to generate a
..                                FASTA sequence.

.. warning::
    This tool is deprecated, and will be removed in future versions of PALEOMIX.


paleomix vcf_filter
-------------------

.. TODO:
..    paleomix vcf_filter       -- Quality filters for VCF records, similar to
..                                 'vcfutils.pl varFilter'.


paleomix vcf_to_fasta
---------------------
.. The 'paleomix vcf\_to\_fasta' command is used to generate FASTA sequences from a VCF file, based either on a set of BED coordinates provided by the user, or for the entire genome covered by the VCF file. By default, heterzyous SNPs are represented using IUPAC codes; if a haploized sequence is desire, random sampling of heterozygous sites may be enabled.


paleomix cat
------------

The 'paleomix cat' command provides a simple wrapper around the commands 'cat', 'gzip', and 'bzip2', calling each as appropriate depending on the files listed on the command-line. This tool is primarily used in order to allow the on-the-fly decompression of input for various programs that do not support both gzip and bzip2 compressed input.

**Usage:**

    usage: paleomix cat [options] files

    positional arguments:
      files            One or more input files; these may be uncompressed,
                       compressed using gzip, or compressed using bzip2.

    optional arguments:
      -h, --help       show this help message and exit
      --output OUTPUT  Write output to this file; by default, output
                       written to STDOUT.


**Example:**

.. code-block:: bash

    $ echo "Simple file" > file1.txt
    $ echo "Gzip'ed file" | gzip > file2.txt.gz
    $ echo "Bzip2'ed file" | bzip2  > file3.txt.bz2
    $ paleomix cat file1.txt file2.txt.gz file3.txt.bz2
    Simple file
    Gzip'ed file
    Bzip2'ed file

.. warning:

    The 'paleomix cat' command works by opening the input files sequentually, identifying the compression scheme, and then calling the appropriate command. Therefore this command only works on regular files, but not on (named) pipes.

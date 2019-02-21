""" Read Manatee files"""
from __future__ import print_function

from collections import defaultdict
import os

import mirtop.libs.logger as mylog
from mirtop.bam.bam import intersect
from mirtop.bam import filter
from mirtop.mirna.realign import isomir, reverse_complement, make_id
from mirtop.gff.body import paste_columns, variant_with_nt
# from mirtop.mirna import mapper
from mirtop.gff.classgff import feature

logger = mylog.getLogger(__name__)


def read_file(fn, database, args):
    """
    Read Manatee file and convert to mirtop GFF format.

    Args:
        *fn(str)*: file name with Manatee output information.

        *database(str)*: database name.

        *args(namedtuple)*: arguments from command line.
            See *mirtop.libs.parse.add_subparser_gff()*.

    Returns:
        *reads (nested dicts)*:gff_list has the format as
            defined in *mirtop.gff.body.read()*.

    """
    reads = defaultdict(dict)
    sample = os.path.splitext(os.path.basename(fn))[0]
    precursors = args.precursors
    bed_fn = os.path.join(args.out, os.path.basename(fn) + ".bed")
    sep = " " if args.out_format == "gtf" else "="
    seen = set()
    with open(fn, 'r') as handle:
        _bed(handle, bed_fn)
    intersect_fn = intersect(bed_fn, args.gtf)
    for line in intersect_fn:
        data = _analyze_line(line, precursors, database, sample, sep, args)
        if data:
            start = data["start"]
            chrom = data["chrom"]
            key = "%s:%s:%s" % (chrom, start, data["line"][0])
            if start not in reads[chrom]:
                reads[chrom][start] = []
            if key not in seen:
                seen.add(key)
                reads[chrom][start].append(data["line"])
    return reads


def _analyze_line(line, precursors, database, sample, sep, args):
    start_idx = 10
    end_idx = 11
    attr_idx = 15
    if str(line).find("miRNA_primary_transcript") < 0: # only working with mirbase
        return None

    query_name = line[3]
    sequence = line[4]
    logger.debug(("READ::line name:{0}").format(line))
    if sequence and sequence.find("N") > -1:
        return None

    chrom = line[attr_idx].strip().split("Name=")[-1]
    start = line[1]
    end = line[2]
    strand = line[5]
    counts = int(line[6])
    Filter = "Pass"
    if not start:
        return None
    if strand == "+":
        start = int(start) - int(line[start_idx]) + 1
    else:
        start = int(line[end_idx]) - int(end)
    iso = isomir()
    iso.align = line
    iso.set_pos(start, len(sequence))
    logger.debug("READ::From BAM start %s end %s at chrom %s" % (iso.start, iso.end, chrom))
    if len(precursors[chrom]) < start + len(sequence):
        logger.debug("READ::%s start + %s sequence size are bigger than"
                     " size precursor %s" % (
                                             chrom,
                                             len(sequence),
                                             len(precursors[chrom])))
    iso.subs, iso.add, iso.cigar = filter.tune(
        sequence, precursors[chrom],
        start, None)
    logger.debug("READ::After tune start %s end %s" % (iso.start, iso.end))
    logger.debug("READ::iso add %s iso subs %s" % (iso.add, iso.subs))

    cigar = iso.cigar
    idu = make_id(sequence)
    isoformat = iso.formatGFF()
    mirna = iso.mirna
    source = "isomiR" if isoformat != "NA" else "ref_miRNA"
    read = sequence if not args.keep_name else query_name
    attrb = ("Read {read}; UID {idu}; Name {mirna};"
             " Parent {chrom}; Variant {isoformat};"
             " Cigar {cigar}; Expression {counts};"
             " Filter {Filter};").format(**locals())
    line = ("{chrom}\t{database}\t{source}\t{start}\t{end}\t"
            ".\t{strand}\t.\t{attrb}").format(**locals())
    logger.debug("READ::line:%s" % line)
    if args.add_extra:
        extra = variant_with_nt(line, args.precursors,
                                args.matures)
        line = "%s Changes %s;" % (line, extra)

    line = paste_columns(feature(line), sep=sep)
    return {'chrom': chrom,
            'start': start,
            'line': [idu, chrom, counts, sample, line]}


def _bed(handle, bed_fn):
    with open(bed_fn, 'w') as outh:
        for line in handle:
            if line.startswith("@"):
                continue
            cols = line.strip().split()
            query_name = cols[0]
            query_sequence = cols[9]
            counts = cols[14]
            start = int(cols[3])
            strand = cols[1]
            chrom = cols[2]
            # is there no hits
            # if line.reference_id < 0:
            #     logger.debug("READ::Sequence not mapped: %s" % line.reference_id)
            #     continue
            # is the sequence always matching the read, assuming YES now
            # if not current or query_name!=current:
            query_sequence = query_sequence if not strand=="-" else reverse_complement(query_sequence)
            # logger.debug(("READ::Read name:{0} and Read sequence:{1}").format(line.query_name, sequence))
            if query_sequence and query_sequence.find("N") > -1:
                continue
            end = start + len(query_sequence) - 1
            bed_line = "\t".join(map(str, [chrom, start, end, query_name,
                                           query_sequence, strand, counts]))
            outh.write(bed_line + '\n')
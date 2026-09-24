"""Synthetic contract tests for the scope-aware evidence packet builder.

The fixture is intentionally self-contained.  It does not read any project
netlist, FM377 artifact, report, or previous run output.
"""

import copy
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCOPE_PACKET_PATH = ROOT / "skills" / "analog-recovery-evidence" / "scripts" / "scope_packet.py"
SPEC = importlib.util.spec_from_file_location("recovery_scope_packet", SCOPE_PACKET_PATH)
if SPEC is None or SPEC.loader is None:
    raise ImportError(f"cannot load scope packet builder: {SCOPE_PACKET_PATH}")
SCOPE_PACKET = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCOPE_PACKET)
make_packet = SCOPE_PACKET.make_packet


def _binding(formal_net_ref, source_net_ref, resolved_net):
    return {
        "formal_net_ref": formal_net_ref,
        "source_net_ref": source_net_ref,
        "resolved_net": resolved_net,
    }


def _fixture_ir():
    """Build a small hierarchical graph with deliberately colliding names."""
    return {
        "definitions": [
            {"id": "def_top", "raw_name": "TOP", "canonical_name": "top"},
            {"id": "def_child", "raw_name": "CHILD", "canonical_name": "child"},
            {"id": "def_other", "raw_name": "OTHER", "canonical_name": "other"},
        ],
        "nets": [
            {
                "id": "net_top_vdd",
                "scope_ref": "def_top",
                "raw_name": "VDD",
                "canonical_name": "supply",
            },
            {
                "id": "net_top_aux",
                "scope_ref": "def_top",
                "raw_name": "AUX",
                "canonical_name": "aux",
            },
            {
                "id": "net_child_vdd",
                "scope_ref": "def_child",
                "raw_name": "VDD",
                "canonical_name": "supply",
            },
            {
                "id": "net_child_aux",
                "scope_ref": "def_child",
                "raw_name": "AUX",
                "canonical_name": "aux",
            },
            {
                "id": "net_other_vdd",
                "scope_ref": "def_other",
                "raw_name": "VDD",
                "canonical_name": "supply",
            },
        ],
        "instances": [
            {
                "id": "inst_a",
                "definition_scope_ref": "def_top",
                "raw_name": "U_A",
                "ordered_terminals": [
                    {"ordinal": 0, "net_ref": "net_top_vdd"},
                    {"ordinal": 1, "net_ref": "net_top_aux"},
                ],
                "span_refs": [],
            },
            {
                "id": "inst_b",
                "definition_scope_ref": "def_top",
                "raw_name": "U_B",
                "ordered_terminals": [
                    {"ordinal": 0, "net_ref": "net_top_vdd"},
                    {"ordinal": 1, "net_ref": "net_top_aux"},
                ],
                "span_refs": [],
            },
            {
                "id": "inst_child_load",
                "definition_scope_ref": "def_child",
                "raw_name": "M_LOAD",
                "ordered_terminals": [
                    {"ordinal": 0, "net_ref": "net_child_vdd"},
                ],
                "span_refs": [],
            },
        ],
        "occurrences": [
            {
                "id": "occ_top",
                "instance_path": "/TOP",
                "definition_ref": "def_top",
                "parent_ref": None,
                "instance_ref": "inst_top",
                "port_bindings": [
                    _binding("net_top_vdd", "net_top_vdd", "VDD"),
                ],
                "status": "complete",
            },
            {
                "id": "occ_a",
                "instance_path": "/TOP/U_A",
                "definition_ref": "def_child",
                "parent_ref": "occ_top",
                "instance_ref": "inst_a",
                "port_bindings": [
                    _binding("net_child_vdd", "net_top_vdd", "VDD"),
                    _binding("net_child_aux", "net_top_aux", "AUX"),
                ],
                "status": "complete",
            },
            {
                "id": "occ_b",
                "instance_path": "/TOP/U_B",
                "definition_ref": "def_child",
                "parent_ref": "occ_top",
                "instance_ref": "inst_b",
                "port_bindings": [
                    # Same formal child net name, but this child is tied to AUX.
                    # It must not become a boundary for TOP/VDD.
                    _binding("net_child_vdd", "net_top_aux", "AUX"),
                ],
                "status": "complete",
            },
        ],
    }


def _refs(rows, key):
    """Accept either the compact string or explicit ``{key: ...}`` form."""
    return [row if isinstance(row, str) else row[key] for row in rows]


def _boundary_binding(row):
    """Read the original binding whether wrapped with provenance or inline."""
    return row.get("binding", row)


class ScopePacketTests(unittest.TestCase):
    def test_cross_definition_same_named_nets_stay_separate(self):
        packet = make_packet(_fixture_ir(), "/TOP", "VDD")

        self.assertEqual(
            {key: packet["selected"][key]
             for key in ("occurrence_ref", "definition_ref", "net_ref")},
            {
                "occurrence_ref": "occ_top",
                "definition_ref": "def_top",
                "net_ref": "net_top_vdd",
            },
        )
        self.assertEqual(
            set(_refs(packet["connections"], "instance_ref")),
            {"inst_a", "inst_b"},
        )
        self.assertNotIn("inst_child_load", _refs(packet["connections"], "instance_ref"))
        self.assertEqual(
            {(row["definition_ref"], row["net_ref"])
             for row in packet["other_same_named_nets"]},
            {
                ("def_child", "net_child_vdd"),
                ("def_other", "net_other_vdd"),
            },
        )

    def test_same_definition_instances_are_selected_by_distinct_paths(self):
        ir = _fixture_ir()
        packet_a = make_packet(ir, "occ_a", "net_child_vdd")
        packet_b = make_packet(ir, "/TOP/U_B", "supply")

        self.assertEqual(packet_a["selected"]["definition_ref"], "def_child")
        self.assertEqual(packet_b["selected"]["definition_ref"], "def_child")
        self.assertEqual(packet_a["selected"]["net_ref"], "net_child_vdd")
        self.assertEqual(packet_b["selected"]["net_ref"], "net_child_vdd")
        self.assertEqual(packet_a["selected"]["occurrence_ref"], "occ_a")
        self.assertEqual(packet_b["selected"]["occurrence_ref"], "occ_b")

        boundaries_a = {(_boundary_binding(b)["formal_net_ref"],
                         _boundary_binding(b)["source_net_ref"])
                        for b in packet_a["boundaries"]}
        boundaries_b = {(_boundary_binding(b)["formal_net_ref"],
                         _boundary_binding(b)["source_net_ref"])
                        for b in packet_b["boundaries"]}
        self.assertIn(("net_child_vdd", "net_top_vdd"), boundaries_a)
        self.assertIn(("net_child_vdd", "net_top_aux"), boundaries_b)

    def test_only_explicit_matching_child_binding_becomes_top_boundary(self):
        packet = make_packet(_fixture_ir(), "occ_top", "net_top_vdd")
        boundaries = {(_boundary_binding(b)["formal_net_ref"],
                       _boundary_binding(b)["source_net_ref"])
                      for b in packet["boundaries"]}

        self.assertIn(("net_top_vdd", "net_top_vdd"), boundaries)
        self.assertIn(("net_child_vdd", "net_top_vdd"), boundaries)
        # The second child has a same-named formal net, but its explicit source
        # is AUX.  Name equality alone must not introduce a boundary.
        self.assertNotIn(("net_child_vdd", "net_top_aux"), boundaries)

    def test_ambiguous_occurrence_selector_is_rejected(self):
        ir = _fixture_ir()
        duplicate = copy.deepcopy(ir["occurrences"][1])
        duplicate["instance_path"] = "/TOP/U_A_ALIAS"
        ir["occurrences"].append(duplicate)

        with self.assertRaises(ValueError):
            make_packet(ir, "occ_a", "net_child_vdd")

    def test_ambiguous_net_selector_is_rejected(self):
        ir = _fixture_ir()
        duplicate = copy.deepcopy(ir["nets"][0])
        duplicate["id"] = "net_top_vdd_duplicate"
        ir["nets"].append(duplicate)

        with self.assertRaises(ValueError):
            make_packet(ir, "occ_top", "VDD")

    def test_incomplete_occurrence_is_local_only_without_boundaries(self):
        ir = _fixture_ir()
        ir["occurrences"][0]["status"] = "incomplete"

        packet = make_packet(ir, "occ_top", "net_top_vdd")
        self.assertTrue(packet["local_only"])
        self.assertEqual(packet["occurrence_status"], "incomplete")
        self.assertEqual(packet["boundaries"], [])
        self.assertEqual(
            set(_refs(packet["connections"], "instance_ref")),
            {"inst_a", "inst_b"},
        )

    def test_missing_occurrence_and_unknown_net_are_rejected(self):
        ir = _fixture_ir()
        with self.assertRaises(ValueError):
            make_packet(ir, "/TOP/MISSING", "net_top_vdd")
        with self.assertRaises(ValueError):
            make_packet(ir, "/TOP", "DOES_NOT_EXIST")


class CompactScopeTests(unittest.TestCase):
    def test_grouping_preserves_members_and_parameter_differences(self):
        row = {'master':'nmos','ordered_terminals':[{'ordinal':1,'net_ref':'n'}],
               'parameters':[{'raw_key':'w','raw_expr':'1u'}],
               'instance_ref':'m1','instance_path':'/A/m1','span_refs':['s1']}
        second = copy.deepcopy(row)
        second.update(instance_ref='m2',instance_path='/A/m2',span_refs=['s2'])
        third = copy.deepcopy(row)
        third.update(instance_ref='m3',instance_path='/A/m3',span_refs=['s3'])
        third['parameters'][0]['raw_expr'] = '2u'
        out = SCOPE_PACKET.compact_packet({'selected':{'net_ref':'n'},'connections':[row,second,third]})
        self.assertEqual(out['connection_count'],3)
        self.assertEqual(len(out['connection_groups']),2)
        self.assertEqual([m['instance_ref'] for m in out['connection_groups'][0]['members']],['m1','m2'])


if __name__ == "__main__":
    unittest.main()

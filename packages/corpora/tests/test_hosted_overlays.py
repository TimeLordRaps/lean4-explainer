"""The real Pages-only overlays stay content-bound, parseable, and outside packages."""

import json
import re

from pathlib import Path

from lean4_explainer_corpora.overlays import load_overlay_manifest
from lean4_explainer_corpora.registry import select
from lean4_explainer_l4del.grammar import parse_l4del
from lean4_explainer_l4del.overlay import parse_overlay


ROOT = Path(__file__).resolve().parents[3]
HOSTED = ROOT / "hosted" / "overlays"
# Generated entries for synthesized anonymous names such as `(example at line 4)` are not emitted: the renderer ignores them.
EXPECTED = {
    "alphaproof-nexus": 721,
    "carleson": 991,
    "compfiles": 3313,
    "flt": 1212,
    "formal-conjectures": 7200,
    "mil": 16,
    "oai": 1393,
    "pfr": 494,
    "tpil": 35,
}
CURATED = {
    "alphaproof-nexus": 348,  # 281 + 67 curated annotations copied to their identical copies
    "carleson": 10,
    "compfiles": 8,
    "flt": 8,
    "formal-conjectures": 10,
    "mil": 9,
    "oai": 120,
    "pfr": 9,
    "tpil": 8,
}


def test_real_hosted_overlays_are_bound_parseable_and_annotation_rich():
    selected = load_overlay_manifest(HOSTED / "manifest.json", select("all"))
    assert set(selected) == set(EXPECTED)

    counts = {}
    errors = []
    for name, hosted in selected.items():
        assert hosted.path.parent == HOSTED
        assert hosted.provenance == "ai-generated-unreviewed"
        assert "GPT-5.6 Sol" in hosted.disclosure and "ultra reasoning" in hosted.disclosure
        if name == "alphaproof-nexus":
            assert "Claude" not in hosted.disclosure
        else:
            assert "Claude Sonnet 5.5" in hosted.disclosure and "medium effort" in hosted.disclosure
        assert "max reasoning" not in hosted.disclosure and "extra-high" not in hosted.disclosure
        assert hosted.curated_annotations == CURATED[name]
        assert hosted.source_derived_annotations == EXPECTED[name] - CURATED[name]
        assert len(hosted.sources) >= 2
        assert all(url.startswith("https://") for _, url in hosted.sources)
        overlay = parse_overlay(hosted.path.read_text(encoding="utf-8"), str(hosted.path))
        counts[name] = sum(len(declarations) for declarations in overlay.files.values())
        for file, declarations in overlay.files.items():
            for declaration, directives in declarations.items():
                notes = parse_l4del(directives)
                errors.extend(
                    f"{name}:{file}:{declaration}:{diagnostic.line}: {diagnostic.message}"
                    for diagnostic in notes.diagnostics
                    if diagnostic.severity == "error"
                )

    assert not errors
    assert counts == EXPECTED
    assert sum(counts.values()) == 15_375


def test_formal_conjectures_overlay_does_not_publish_a_partial_glossary():
    overlay = parse_overlay(
        (HOSTED / "formal-conjectures.l4del").read_text(encoding="utf-8"),
        str(HOSTED / "formal-conjectures.l4del"),
    )

    terms = [
        term
        for declarations in overlay.files.values()
        for directives in declarations.values()
        for term in parse_l4del(directives).terms
    ]
    assert terms == []


def test_hosted_overlays_do_not_publish_generator_control_markers():
    forbidden = (
        "evolve-block-start",
        "evolve-block-end",
        "begin generated",
        "end generated",
        "put your definitions and lemmas here",
    )

    leaked: list[tuple[str, str, str, str]] = []
    for overlay_path in sorted(HOSTED.glob("*.l4del")):
        overlay = parse_overlay(overlay_path.read_text(encoding="utf-8"), str(overlay_path))
        for relative_path, declarations in overlay.files.items():
            for declaration, directives in declarations.items():
                explanation = parse_l4del(directives)
                visible_text = "\n".join(
                    part
                    for part in (
                        explanation.title,
                        explanation.intuition,
                        *explanation.steps,
                        *(name for name, _ in explanation.terms),
                        *(definition for _, definition in explanation.terms),
                        *(excerpt for _, excerpt in explanation.quotes),
                    )
                    if part
                ).casefold()
                for marker in forbidden:
                    if marker in visible_text:
                        leaked.append((overlay_path.name, relative_path, declaration, marker))

    assert leaked == []


def test_featured_manuscript_annotations_bind_quotes_to_named_sources():
    targets = (
        (
            "alphaproof-nexus.l4del",
            "APNOutputs/OEIS/oeis_51293_conjecture_0.lean",
            "target_theorem_0",
            "Human-written proof companion for OEIS A051293",
        ),
        (
            "alphaproof-nexus.l4del",
            "APNOutputs/ErdosProblems/erdos_152.lean",
            "Erdos152.target_theorem_0",
            "Human-written proof companion for Erdős 152",
        ),
        (
            "alphaproof-nexus.l4del",
            "APNOutputs/AICollaborator/AdditiveCombinatorics/57.lean",
            "Green57.green_57",
            "Ben Green, 100 Open Problems, Problem 57",
        ),
        (
            "alphaproof-nexus.l4del",
            "APNOutputs/AICollaborator/Optimization/LastIterateConvergence.lean",
            "Arxiv.«1905.10899».last_iterate_convergence",
            "Anja Surina et al., improved anchored-GDA paper (2026)",
        ),
        (
            "alphaproof-nexus.l4del",
            "APNOutputs/AICollaborator/Graphs/GraphConjecture2.lean",
            "WrittenOnTheWallII.GraphConjecture2.conjecture2",
            "George Tsoukalas et al., AlphaProof Nexus paper (Appendix I)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/MatrixMultiplication.lean",
            "OAI.MatrixMultiplication.complex_omega_le_nine_quarters",
            "OpenAI 9/4 manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/QuasiRiemannHypothesis.lean",
            "OAI.riemannZeta_ne_zero_of_seven_eighths_lt_re",
            "OpenAI quasi-Riemann manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/HadwigerCounterexample.lean",
            "OAI.HadwigerCounterexample.exists_counterexamples",
            "OpenAI Hadwiger-counterexample manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/KaplanskyDirectFiniteness.lean",
            "OAI.KaplanskyCounterexample.main_theorem",
            "OpenAI Kaplansky counterexample manuscript (p. 1)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/MahlerConjecture.lean",
            "OAI.SymmetricMahler.symmetric_mahler",
            "OpenAI symmetric-Mahler manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/AffineBernstein.lean",
            "OAI.AffineBernstein.affine_bernstein",
            "OpenAI affine-Bernstein manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/UniqueGamesTheorem.lean",
            "OAI.UniqueGamesTheorem.theorem11",
            "OpenAI Unique Games manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/YauCounterexample.lean",
            "OAI.Yau.Target.yau_nodal_set_upper_bound_counterexample",
            "OpenAI Yau power-law counterexample manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/SeymourSecondNeighborhood.lean",
            "OAI.SeymourSecondNeighborhood.exists_goodVertex",
            "OpenAI Seymour second-neighborhood manuscript",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/CannonGeometricAction.lean",
            "OAI.CannonRelease.cannon",
            "OpenAI Cannon manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/KoebeCircleDomains.lean",
            "OAI.Problem047.koebe_circle_domain",
            "OpenAI Koebe circle-domain manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/KoebeCircleDomains.lean",
            "OAI.Problem047.removability_implies_rigidity",
            "OpenAI circle-domain rigidity manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/ThreeTorus.lean",
            "OAI.ThreeTorus.simple_lebesgue_spectrum",
            "OpenAI simple-Lebesgue-spectrum manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/Rokhlin.lean",
            "OAI.Rokhlin.mixing_all_finite_orders",
            "OpenAI Rokhlin multiple-mixing manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/BorsukNine.lean",
            "OAI.BorsukNine.main_theorem",
            "OpenAI nine-dimensional Borsuk manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/TingleySphereIsometry.lean",
            "OAI.Tingley.tingley_sphere_isometry_full",
            "OpenAI Tingley manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/AbhyankarSathaye.lean",
            "OAI.AbhyankarSathaye.exists_noncoordinate_polynomial",
            "OpenAI Abhyankar-Sathaye counterexample manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/CirculantHadamard.lean",
            "OAI.CirculantHadamard.exists_iff_order_one_or_four",
            "OpenAI circulant-Hadamard manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/EilenbergGanea.lean",
            "OAI.EilenbergGanea.source_main",
            "OpenAI Eilenberg-Ganea counterexample manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/ShortEgyptianFractions.lean",
            "OAI.ShortEgyptian.main",
            "OpenAI short-Egyptian-fractions manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/CompleteCrouzeix.lean",
            "OAI.CompleteCrouzeix.main",
            "OpenAI complete-Crouzeix manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/EuclideanFiveColor.lean",
            "OAI.EuclideanFiveColor.no_proper_five_coloring",
            "OpenAI Euclidean-five-color manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/GeneralMahler.lean",
            "OAI.GeneralMahler.general_mahler",
            "OpenAI general-Mahler manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/ThompsonNonamenability.lean",
            "OAI.ThompsonNonamenability.thompson_F_nonamenable_composition",
            "OpenAI Thompson-F manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/AlgorithmicThinTrees.lean",
            "OAI.AlgorithmicThinTrees.algorithmic_strong_thin_trees",
            "Nima Anari, Thin Trees and Interlacing Families lecture slides (Simons Institute)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/BarnetteHamiltonian.lean",
            "OAI.Barnette.main",
            "OpenAI Barnette manuscript (abstract)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/ArtinCAT0.lean",
            "OAI.ArtinCAT0.main",
            "Ruth Charney, An introduction to right-angled Artin groups (2007)",
        ),
        (
            "oai.l4del",
            "ComparatorChallenges/AmplitudeDamping.lean",
            "OAI.GAD.main",
            "Sumeet Khatri, Kunal Sharma, and Mark M. Wilde, Information-theoretic aspects of GAD (2020)",
        ),
    )

    for overlay_name, relative_path, declaration, expected_source in targets:
        overlay_path = HOSTED / overlay_name
        overlay = parse_overlay(overlay_path.read_text(encoding="utf-8"), str(overlay_path))
        notes = parse_l4del(overlay.files[relative_path][declaration])
        source_labels = {label for label, _ in notes.sources}
        quote_labels = {label for label, _ in notes.quotes}

        assert notes.title and notes.intuition and len(notes.steps) >= 3
        assert expected_source in source_labels
        assert expected_source in quote_labels
        assert quote_labels <= source_labels


def test_manuscript_source_ledger_binds_pdf_bytes_pages_quotes_and_targets():
    ledger = json.loads((HOSTED / "manuscript-sources.json").read_text(encoding="utf-8"))
    manifest = json.loads((HOSTED / "manifest.json").read_text(encoding="utf-8"))["overlays"]
    assert ledger["schema"] == 1
    assert len(ledger["sources"]) == 46

    overlays = {}
    targets = set()
    citation_coordinates = set()
    pinned_citations = 0
    source_coordinates = set()
    for source in ledger["sources"]:
        corpus = source["corpus"]
        source_coordinate = (corpus, source["path"])
        assert source_coordinate not in source_coordinates
        source_coordinates.add(source_coordinate)
        assert source["repo"] == manifest[corpus]["repo"]
        assert source["commit"] == manifest[corpus]["commit"]
        assert re.fullmatch(r"[0-9a-f]{64}", source["sha256"])
        assert source["path"].endswith(".pdf") and ".." not in Path(source["path"]).parts
        assert source["url"].startswith(
            f"https://github.com/{source['repo']}/blob/{source['commit']}/"
        )

        if corpus not in overlays:
            overlay_path = HOSTED / f"{corpus}.l4del"
            overlays[corpus] = parse_overlay(
                overlay_path.read_text(encoding="utf-8"), str(overlay_path)
            )
        for citation in source["citations"]:
            target = (corpus, citation["file"], citation["declaration"])
            targets.add(target)
            citation_coordinate = (
                corpus,
                source["path"],
                citation["file"],
                citation["declaration"],
                citation["page"],
                citation["quote"],
            )
            assert citation_coordinate not in citation_coordinates
            citation_coordinates.add(citation_coordinate)
            pinned_citations += 1
            assert citation["page"] >= 1
            assert 1 <= len(citation["quote"].split()) <= 25
            notes = parse_l4del(
                overlays[corpus].files[citation["file"]][citation["declaration"]]
            )
            source_label = citation.get("source_label", source["source_label"])
            assert isinstance(source_label, str) and source_label
            assert (source_label, source["url"]) in notes.sources
            assert (source_label, citation["quote"]) in notes.quotes

    assert len(targets) == 308  # 242 + the 11 Hilbert definitions copied to each of hilbert_functions_1, _2, _3, _4, _7, _8
    assert pinned_citations == 309

    external_sources = ledger["external_sources"]
    assert len(external_sources) == 23
    external_citations = 0
    for source in external_sources:
        assert source["corpus"] in manifest
        assert source["url"].startswith("https://")
        assert source["pdf_url"].startswith("https://")
        assert re.fullmatch(r"[0-9a-f]{64}", source["sha256"])
        assert source["cache_file"] == Path(source["cache_file"]).name
        assert source["cache_file"].endswith(".pdf")
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", source["retrieved_at"])
        if source["corpus"] not in overlays:
            overlay_path = HOSTED / f"{source['corpus']}.l4del"
            overlays[source["corpus"]] = parse_overlay(
                overlay_path.read_text(encoding="utf-8"), str(overlay_path)
            )
        for citation in source["citations"]:
            external_citations += 1
            assert citation["page"] >= 1
            assert 1 <= len(citation["quote"].split()) <= 25
            notes = parse_l4del(
                overlays[source["corpus"]].files[citation["file"]][citation["declaration"]]
            )
            assert (citation["source_label"], source["url"]) in notes.sources
            assert (citation["source_label"], citation["quote"]) in notes.quotes

    assert external_citations == 74  # 61 + OrderIdeal and pureOSequence in six more Hilbert files, IsGood in erdos_12.parts.ii


def test_graph_reconstruction_companion_grounds_the_checked_proof_spine():
    overlay_path = HOSTED / "alphaproof-nexus.l4del"
    overlay = parse_overlay(overlay_path.read_text(encoding="utf-8"), str(overlay_path))
    declarations = overlay.files[
        "APNOutputs/AICollaborator/Graphs/bipartite_graph_reconstruction_conjecture_2.lean"
    ]

    result = parse_l4del(declarations["Conjecture2"])
    assert any("G_not_regular" in step and "redundant" in step for step in result.steps)
    assert any("Paul J. Kelly" in label for label, _ in result.quotes)
    assert any("Bondy and R. L. Hemminger" in label for label, _ in result.quotes)

    deck = parse_l4del(declarations["bipartiteDeck"])
    assert "remains as an isolated vertex" in deck.intuition

    edge_count = parse_l4del(declarations["bipartiteDeck_determines_edgeCount"])
    assert "n−2" in edge_count.intuition

    profile = parse_l4del(declarations["profile_eq_of_iso"])
    assert any("eventual zero counts" in step for step in profile.steps)

    neighboring_types = parse_l4del(declarations["S_multiset_eq"])
    assert "highest degrees downward" in neighboring_types.intuition

    adjacency = parse_l4del(declarations["count_typeProfile_eq_one_iff_adj"])
    assert "profile membership into adjacency" in adjacency.title

    final_upgrade = parse_l4del(declarations["type_preserving_bijection_is_iso"])
    assert "BipartiteIso" in final_upgrade.intuition


def test_seymour_manuscript_grounds_the_solution_proof_spine():
    overlay_path = HOSTED / "oai.l4del"
    overlay = parse_overlay(overlay_path.read_text(encoding="utf-8"), str(overlay_path))

    second_neighbors = parse_l4del(
        overlay.files["OAI/Combinatorics/SecondNeighborhood/Model.lean"][
            "OAI.SeymourSecondNeighborhood.secondNeighbors"
        ]
    )
    assert "exact distance two" in second_neighbors.intuition

    subset_deficit = parse_l4del(
        overlay.files["OAI/Combinatorics/SecondNeighborhood/SubsetDeficit.lean"][
            "OAI.SeymourSecondNeighborhood.subsetDeficit_of_minimal"
        ]
    )
    assert any("Tyler Seacrest" in label for label, _ in subset_deficit.quotes)

    blowup = parse_l4del(
        overlay.files["OAI/Combinatorics/SecondNeighborhood/TransitiveBlowup.lean"][
            "OAI.SeymourSecondNeighborhood.blowup_strictSubsetGrowth"
        ]
    )
    assert any("James Brantner" in label for label, _ in blowup.quotes)

    pruning = parse_l4del(
        overlay.files["OAI/Combinatorics/SecondNeighborhood/Pruning.lean"][
            "OAI.SeymourSecondNeighborhood.Pruning.pruning"
        ]
    )
    assert any("augmented bipartite matching" in step for step in pruning.steps)

    extremal = parse_l4del(
        overlay.files["OAI/Combinatorics/SecondNeighborhood/ExtremalContradiction.lean"][
            "OAI.SeymourSecondNeighborhood.Extremal.no_strictSubsetGrowth_of_pruning"
        ]
    )
    assert "No nonempty finite oriented graph" in extremal.intuition

    solution = parse_l4del(
        overlay.files["OAI/Combinatorics/SecondNeighborhood/Main.lean"][
            "OAI.SeymourSecondNeighborhood.exists_goodVertex"
        ]
    )
    assert "comparator declaration" in solution.intuition
    assert "checked proof term" in solution.intuition


def test_curated_oai_annotations_preserve_the_new_statement_boundaries():
    overlay_path = HOSTED / "oai.l4del"
    overlay = parse_overlay(overlay_path.read_text(encoding="utf-8"), str(overlay_path))

    abhyankar = parse_l4del(
        overlay.files["ComparatorChallenges/AbhyankarSathaye.lean"][
            "OAI.AbhyankarSathaye.exists_noncoordinate_polynomial"
        ]
    )
    assert "dimension at least four" in abhyankar.intuition
    assert any("does not claim a three-variable counterexample" in step for step in abhyankar.steps)

    circulant = parse_l4del(
        overlay.files["ComparatorChallenges/CirculantHadamard.lean"][
            "OAI.CirculantHadamard.exists_iff_order_one_or_four"
        ]
    )
    assert "positive-order" in circulant.intuition
    assert any("Barker-sequence corollary" in step and "separate" in step for step in circulant.steps)

    eilenberg_ganea = parse_l4del(
        overlay.files["ComparatorChallenges/EilenbergGanea.lean"][
            "OAI.EilenbergGanea.source_main"
        ]
    )
    assert any("SourceGroup" in step for step in eilenberg_ganea.steps)
    assert any("two-dimensional" in step and "rule out" in step for step in eilenberg_ganea.steps)

    egyptian = parse_l4del(
        overlay.files["ComparatorChallenges/ShortEgyptianFractions.lean"][
            "OAI.ShortEgyptian.main"
        ]
    )
    assert "log(log b)" in egyptian.intuition
    assert any("existential rather than explicit" in step for step in egyptian.steps)

    crouzeix = parse_l4del(
        overlay.files["ComparatorChallenges/CompleteCrouzeix.lean"][
            "OAI.CompleteCrouzeix.main"
        ]
    )
    assert "no smaller constant works uniformly" in crouzeix.intuition
    assert any(
        "finite-matrix comparator" in step and "Hilbert-space" in step
        for step in crouzeix.steps
    )

    five_color = parse_l4del(
        overlay.files["ComparatorChallenges/EuclideanFiveColor.lean"][
            "OAI.EuclideanFiveColor.no_proper_five_coloring"
        ]
    )
    assert "measurability" in five_color.intuition
    assert any(
        "does not contain the separate seven-color construction" in step
        for step in five_color.steps
    )

    general_mahler = parse_l4del(
        overlay.files["ComparatorChallenges/GeneralMahler.lean"][
            "OAI.GeneralMahler.general_mahler"
        ]
    )
    assert "Exactly the simplices attain it" in general_mahler.intuition
    assert any(
        "nonsymmetric theorem" in step and "different statement" in step
        for step in general_mahler.steps
    )

    thompson = parse_l4del(
        overlay.files["ComparatorChallenges/ThompsonNonamenability.lean"][
            "OAI.ThompsonNonamenability.thompson_F_nonamenable_composition"
        ]
    )
    assert "positive normalized left-invariant mean" in thompson.intuition
    assert any("no explicit Følner-boundary constant" in step for step in thompson.steps)

    thin_trees = parse_l4del(
        overlay.files["ComparatorChallenges/AlgorithmicThinTrees.lean"][
            "OAI.AlgorithmicThinTrees.algorithmic_strong_thin_trees"
        ]
    )
    assert "deterministic finite stack machine" in thin_trees.intuition
    assert any("parallel multiplicities are compressed in binary" in step for step in thin_trees.steps)
    assert any("comparator declaration ends in `by sorry`" in step for step in thin_trees.steps)

    barnette = parse_l4del(
        overlay.files["ComparatorChallenges/BarnetteHamiltonian.lean"]["OAI.Barnette.main"]
    )
    assert "one cycle visiting every vertex exactly once" in barnette.intuition
    assert any("not a disconnected spanning 2-factor" in step for step in barnette.steps)
    assert any("David Barnette posed the conjecture in 1969" in step for step in barnette.steps)

    artin = parse_l4del(
        overlay.files["ComparatorChallenges/ArtinCAT0.lean"]["OAI.ArtinCAT0.main"]
    )
    assert "116 generators" in artin.intuition
    assert any("not merely one proposed metric" in step for step in artin.steps)
    assert ("CAT", "Cartan-Alexandrov-Toponogov") in artin.acronyms

    amplitude = parse_l4del(
        overlay.files["ComparatorChallenges/AmplitudeDamping.lean"]["OAI.GAD.main"]
    )
    assert "operational unassisted classical capacity" in amplitude.intuition
    assert any("does not state additivity with an arbitrary different partner channel" in step for step in amplitude.steps)
    assert any("Khatri, Sharma, and Wilde" in step for step in amplitude.steps)


def test_algorithmic_thin_trees_explains_the_complete_formal_interface():
    overlay_path = HOSTED / "oai.l4del"
    overlay = parse_overlay(overlay_path.read_text(encoding="utf-8"), str(overlay_path))
    declarations = overlay.files["ComparatorChallenges/AlgorithmicThinTrees.lean"]

    assert len(declarations) == 38

    multigraph = parse_l4del(declarations["OAI.StrongThinTree.MultiGraph"])
    assert "individually indexed edge copies" in multigraph.title
    assert any("Parallel edges are allowed" in step for step in multigraph.steps)

    machine = parse_l4del(declarations["OAI.CurrentKS.Machine"])
    assert "finite Boolean-stack machine" in machine.title
    assert any("formalization's computational model" in step for step in machine.steps)

    binary = parse_l4del(declarations["OAI.AlgorithmicThinTrees.BinaryInput.encode"])
    assert "multiplicity-compressed" in binary.title
    assert any("does not emit one record per edge copy" in step for step in binary.steps)

    thin = parse_l4del(declarations["OAI.AlgorithmicThinTrees.ThinTree"])
    assert "uniformly thin across every cut" in thin.title
    assert any("same `T` must satisfy" in step for step in thin.steps)
    assert any("Luis Goddyn" in label for label, _ in thin.quotes)
    assert any("Nima Anari and Shayan Oveis Gharan" in label for label, _ in thin.quotes)

    proposition = parse_l4del(
        declarations["OAI.AlgorithmicThinTrees.AlgorithmicStrongThinTrees"]
    )
    assert "complete deterministic polynomial-time" in proposition.title
    assert any("currently has body `by sorry`" in step for step in proposition.steps)

    theorem = parse_l4del(
        declarations["OAI.AlgorithmicThinTrees.algorithmic_strong_thin_trees"]
    )
    assert any("comparator declaration ends in `by sorry`" in step for step in theorem.steps)
    assert any("`degree` that may be zero" in step for step in theorem.steps)


def test_multi_result_formalization_notes_do_not_spill_across_declarations():
    overlay_path = HOSTED / "oai.l4del"
    overlay = parse_overlay(overlay_path.read_text(encoding="utf-8"), str(overlay_path))

    directed_feedback = parse_l4del(
        overlay.files["ComparatorChallenges/DirectedFeedback.lean"][
            "OAI.DirectedFeedback.main"
        ]
    )
    assert directed_feedback.title == (
        "Challenge statement: Constant-factor hardness of directed feedback vertex set"
    )
    assert "Unique Games" not in directed_feedback.intuition
    assert any("combined Scope prose is not copied" in step for step in directed_feedback.steps)

    nodal_length = parse_l4del(
        overlay.files["ComparatorChallenges/NodalLength.lean"]["OAI.SharpNodal.Main"]
    )
    assert nodal_length.title == (
        "Challenge statement: Sharp upper bound for nodal length on smooth surfaces"
    )
    assert "S^4" not in nodal_length.intuition and "S⁴" not in nodal_length.intuition
    assert any("combined Scope prose is not copied" in step for step in nodal_length.steps)

    koebe = parse_l4del(
        overlay.files["ComparatorChallenges/KoebeCircleDomains.lean"][
            "OAI.Problem047.koebe_circle_domain"
        ]
    )
    rigidity = parse_l4del(
        overlay.files["ComparatorChallenges/KoebeCircleDomains.lean"][
            "OAI.Problem047.removability_implies_rigidity"
        ]
    )
    assert "removable" not in koebe.intuition.casefold()
    assert "every nonempty connected open subset" in koebe.intuition.casefold()
    assert "conformally removable" in rigidity.intuition.casefold()
    assert "every nonempty connected open subset" not in rigidity.intuition.casefold()


def test_unique_games_file_distinguishes_manuscript_math_from_lean_serialization():
    overlay_path = HOSTED / "oai.l4del"
    overlay = parse_overlay(overlay_path.read_text(encoding="utf-8"), str(overlay_path))
    declarations = overlay.files["ComparatorChallenges/UniqueGamesTheorem.lean"]

    assert len(declarations) == 32

    expected_source_prefix = (
        "https://github.com/openai/math/blob/"
        "fd4aeeb2ee4fc729c18d98444fed42fd0529eeeb/lean/"
        "ComparatorChallenges/UniqueGamesTheorem.lean#L"
    )
    assert all(
        any(
            label == "Pinned OpenAI Lean source for Unique Games"
            and url.startswith(expected_source_prefix)
            for label, url in parse_l4del(directives).sources
        )
        for directives in declarations.values()
    )

    permutation = parse_l4del(
        declarations["OAI.UniqueGamesTheorem.Foundations.Target.PermutationTable"]
    )
    assert "certified inverse" in permutation.title
    assert any("Subhash Khot" in label for label, _ in permutation.quotes)
    assert any("two-table certification is the Lean implementation" in step for step in permutation.steps)

    instance = parse_l4del(
        declarations["OAI.UniqueGamesTheorem.Foundations.Target.Instance"]
    )
    assert "unweighted" in instance.title
    assert any("list occurrences rather than a set" in step for step in instance.steps)

    formula = parse_l4del(declarations["OAI.UniqueGamesTheorem.BinaryFormula.Formula"])
    assert any("not attributed to the paper" in step for step in formula.steps)

    parser = parse_l4del(declarations["OAI.UniqueGamesTheorem.BinaryEncoding.parseName"])
    assert not parser.quotes
    assert any("does not specify this framing" in step for step in parser.steps)

    tapes = parse_l4del(
        declarations[
            "OAI.UniqueGamesTheorem.Foundations.Complexity.MachineFiniteAlphabet.FiniteAlphabet"
        ]
    )
    assert any("not the same proposition" in step for step in tapes.steps)

    contract = parse_l4del(
        declarations[
            "OAI.UniqueGamesTheorem.Explicit.MachineOutputContract.BinaryGapReduction"
        ]
    )
    assert "complete machine-checkable contract" in contract.title
    assert any("not itself the existence proof" in step for step in contract.steps)

    game_bits = parse_l4del(
        declarations["OAI.UniqueGamesTheorem.Foundations.Complexity.gameBits"]
    )
    assert "unary" in game_bits.intuition.casefold()
    assert any("not the logarithmic endpoint encoding" in step for step in game_bits.steps)
    assert not game_bits.quotes

    theorem = parse_l4del(declarations["OAI.UniqueGamesTheorem.theorem11"])
    assert any("Subhash Khot" in label for label, _ in theorem.quotes)
    assert any("`sorry`" in step for step in theorem.steps)


def test_erdos_741i_separates_density_variants_and_explains_the_counterexample():
    overlay_path = HOSTED / "alphaproof-nexus.l4del"
    overlay = parse_overlay(overlay_path.read_text(encoding="utf-8"), str(overlay_path))
    declarations = overlay.files["APNOutputs/ErdosProblems/erdos_741.parts.i.lean"]
    notes = parse_l4del(declarations["Erdos741.target_theorem_0"])

    assert "`answer(False)`" in notes.intuition
    assert "positive ordinary natural-density limit" in notes.intuition
    assert "different, compatible theorem for positive upper density" in notes.intuition
    assert "do not disagree" in notes.intuition
    assert "lower-density variant is separate and remains unresolved" in notes.intuition
    assert any("only a positive limsup is required" in step for step in notes.steps)
    assert (
        "Human-written proof companion for Erdős 741(i)",
        "We show that the answer is yes. We use an alternating block partition.",
    ) in notes.quotes
    assert any("Paul Erdős" in label for label, _ in notes.quotes)
    assert any("Ulam AI" in label for label, _ in notes.quotes)

    counterexample = parse_l4del(declarations["Erdos741.SandorA"])
    assert "all naturals" in counterexample.intuition
    assert any("fixed-factor" in step for step in counterexample.steps)

    digit_coverage = parse_l4del(declarations["Erdos741.B1_add_B2_eq_univ"])
    assert "all naturals" in digit_coverage.intuition

    fluctuation = parse_l4del(declarations["Erdos741.SandorA_fluctuation_bounds"])
    assert "one fixed `delta>0` forever" in fluctuation.intuition
    assert any("incompatible with convergence" in step for step in fluctuation.steps)


def test_erdos_12i_separates_the_companion_construction_from_the_lean_proof():
    overlay_path = HOSTED / "alphaproof-nexus.l4del"
    overlay = parse_overlay(overlay_path.read_text(encoding="utf-8"), str(overlay_path))
    declarations = overlay.files["APNOutputs/ErdosProblems/erdos_12.parts.i.lean"]

    assert len(declarations) == 80

    property_p = parse_l4del(declarations["Erdos12.IsGood"])
    assert "Property P" in property_p.title
    assert any("Paul Erdős and András Sárközy" in label for label, _ in property_p.quotes)

    witness = parse_l4del(declarations["Erdos12.MyGoodSet"])
    assert "congruence-block witness" in witness.title
    assert any("different base-2-to-base-3 block construction" in step for step in witness.steps)

    good = parse_l4del(declarations["Erdos12.my_good_set_is_good"])
    assert any("later block" in step and "q ma" in step for step in good.steps)
    assert any("same block" in step and "mod 3" in step for step in good.steps)

    density = parse_l4del(declarations["Erdos12.density_bound_N"])
    assert "at least `1/3`" in density.intuition
    assert any("completed previous block" in step for step in density.steps)

    upper = parse_l4del(declarations["Erdos12.g_val_inj"])
    assert any("difference divisible by `P m`" in step for step in upper.steps)

    theorem = parse_l4del(declarations["Erdos12.target_theorem_0"])
    assert any("same theorem by a different construction" in step for step in theorem.steps)
    assert any("proof details are not attributed" in step for step in theorem.steps)
    assert all("companion proof builds" not in step for step in theorem.steps)


def test_erdos_125_companion_grounds_the_complete_density_decay_proof():
    overlay_path = HOSTED / "alphaproof-nexus.l4del"
    overlay = parse_overlay(overlay_path.read_text(encoding="utf-8"), str(overlay_path))
    declarations = overlay.files[
        "APNOutputs/ErdosProblems/erdos_125.variants.positive_lower_density.lean"
    ]

    assert len(declarations) == 19

    base_three = parse_l4del(declarations["Erdos125.A_decomp"])
    assert "top and bottom blocks" in base_three.title
    assert any("k-th digit" in quote for _, quote in base_three.quotes)

    approximation = parse_l4del(declarations["Erdos125.dirichlet_approx"])
    assert "nearby powers of three and four" in approximation.title
    assert "`3^k≤4^m≤3^k*(1+ε)`" in approximation.intuition

    contraction = parse_l4del(declarations["Erdos125.scale_step"])
    assert "`(11/12)*C*N'`" in contraction.intuition
    assert any("`5/6+2εN≤11/12`" in step for step in contraction.steps)
    assert any("GTSoukalas" in label for label, _ in contraction.quotes)

    theorem = parse_l4del(declarations["Erdos125.target_theorem_0"])
    assert any("explicit contraction `11/12`" in step for step in theorem.steps)
    assert any("Burr, Erdős, Graham, and Li" in label for label, _ in theorem.quotes)
    assert any("Giuseppe Melfi" in label for label, _ in theorem.quotes)


def test_erdos_138_separates_the_greedy_bound_from_compactness_support():
    overlay_path = HOSTED / "alphaproof-nexus.l4del"
    overlay = parse_overlay(overlay_path.read_text(encoding="utf-8"), str(overlay_path))
    declarations = overlay.files[
        "APNOutputs/ErdosProblems/erdos_138.variants.difference.lean"
    ]

    assert len(declarations) == 29

    ending = parse_l4del(declarations["Erdos138.ap_must_end"])
    assert "must end at the new point" in ending.title

    extension = parse_l4del(declarations["Erdos138.extend_one_step"])
    assert any("`N+i+1-d₀d₁`" in step for step in extension.steps)

    existence = parse_l4del(declarations["Erdos138.W_is_nonempty"])
    assert any("ultrafilter compactness" in step for step in existence.steps)
    assert any("double-induction" in step for step in existence.steps)

    theorem = parse_l4del(declarations["Erdos138.target_theorem_0"])
    assert any("resolves only the difference variant" in step for step in theorem.steps)
    assert any("Paul Erdős" in label for label, _ in theorem.quotes)
    assert any("AlphaProof Nexus paper" in label for label, _ in theorem.quotes)


def test_alphaproof_annotations_credit_historical_and_current_mathematicians():
    overlay_path = HOSTED / "alphaproof-nexus.l4del"
    overlay = parse_overlay(overlay_path.read_text(encoding="utf-8"), str(overlay_path))

    hilbert = parse_l4del(
        overlay.files["APNOutputs/AICollaborator/AlgebraicGeometry/hilbert_functions_5.lean"]["P5"]
    )
    assert (
        "Richard P. Stanley, Hilbert functions of graded algebras (1978)",
        "is said to be an O-sequence if there exists an order ideal M of monomials",
    ) in hilbert.quotes

    order_ideal = parse_l4del(
        overlay.files["APNOutputs/AICollaborator/AlgebraicGeometry/hilbert_functions_5.lean"][
            "OrderIdeal"
        ]
    )
    assert (
        "Richard P. Stanley, Hilbert functions of graded algebras (1978)",
        "is said to be an O-sequence if there exists an order ideal M of monomials",
    ) in order_ideal.quotes

    erdos_846 = parse_l4del(
        overlay.files["APNOutputs/ErdosProblems/erdos_846.lean"][
            "Erdos846.target_theorem_0"
        ]
    )
    assert (
        "Moe Putterman, Mehtaab Sawhney, and Gregory Valiant (2026), arXiv v1 abstract",
        "A cannot be separated into finitely many subsets such that each subset has no three points collinear",
    ) in erdos_846.quotes

    ame = parse_l4del(
        overlay.files["APNOutputs/AICollaborator/QuantumOptics/35.lean"][
            "OpenQuantumProblem35.ame_11_5_open"
        ]
    )
    assert (
        "Wolfram Helwig et al., Absolute Maximal Entanglement and Quantum Secret Sharing (2012)",
        "AME states are characterized by being maximally entangled for all bipartitions of the system",
    ) in ame.quotes
    assert any("underlying Quantum Code was already discovered" in quote for _, quote in ame.quotes)


def test_hilbert_companion_grounds_the_supporting_lean_vocabulary():
    overlay_path = HOSTED / "alphaproof-nexus.l4del"
    overlay = parse_overlay(overlay_path.read_text(encoding="utf-8"), str(overlay_path))
    hilbert = overlay.files[
        "APNOutputs/AICollaborator/AlgebraicGeometry/hilbert_functions_5.lean"
    ]

    order_ideal = parse_l4del(hilbert["OrderIdeal"])
    assert "divisor" in order_ideal.intuition
    assert any("downward_closed" in step for step in order_ideal.steps)
    assert (
        "Human-written Hilbert-functions proof companion",
        "A finite order ideal Γ ⊂ N3 is a finite set closed downward under this order",
    ) in order_ideal.quotes

    purity = parse_l4del(hilbert["IsPure"])
    assert "does not itself assert" in purity.intuition
    assert any("socle degree" in step for step in purity.steps)

    log_concavity = parse_l4del(hilbert["IsLogConcaveUpTo"])
    assert "neighbours" in log_concavity.intuition
    assert any("boundary exclusions" in step for step in log_concavity.steps)


def test_a_declaration_the_source_repeats_has_the_same_annotation_in_every_copy():
    # The build rejects identical copies whose annotations differ ("make the identical copies' annotations match"), but
    # only after a full Lean-backed build. These twelve were once curated in one file and condensed in the other.
    overlay_path = HOSTED / "alphaproof-nexus.l4del"
    overlay = parse_overlay(overlay_path.read_text(encoding="utf-8"), str(overlay_path))
    algebra = "APNOutputs/AICollaborator/AlgebraicGeometry/"
    reference_file = algebra + "hilbert_functions_5.lean"
    hilbert_files = sorted(path for path in overlay.files if path.startswith(algebra + "hilbert_functions_"))
    pairs = [
        (reference_file, path, name)
        for name in (
            "Monomial", "totalDeg", "OrderIdeal", "divisorsFinset", "IsMaximalIn", "IsPure",
            "PureOrderIdeal", "typePO", "socleDegree", "pureOSequence", "IsLogConcaveUpTo",
        )
        for path in hilbert_files
        if path != reference_file and name in overlay.files[path]
    ] + [(
        "APNOutputs/ErdosProblems/erdos_12.parts.i.lean",
        "APNOutputs/ErdosProblems/erdos_12.parts.ii.lean",
        "Erdos12.IsGood",
    )]
    assert len(pairs) == 11 * 6 + 1  # hilbert_functions_1, _2, _3, _4, _7 and _8 repeat the eleven definitions of _5

    def content(path, name):  # the parsed lines carry their line numbers, which differ between files
        return tuple(text for _, text in overlay.files[path][name])

    for first, second, name in pairs:
        assert content(first, name) == content(second, name), (name, first, second)
        assert any(text.startswith(" source:") for text in content(second, name)), (name, second)


def test_hilbert_companion_grounds_the_formal_proof_spine():
    overlay_path = HOSTED / "alphaproof-nexus.l4del"
    overlay = parse_overlay(overlay_path.read_text(encoding="utf-8"), str(overlay_path))
    hilbert = overlay.files[
        "APNOutputs/AICollaborator/AlgebraicGeometry/hilbert_functions_5.lean"
    ]

    assert len(hilbert) == 118

    decomposition = parse_l4del(hilbert["pureOSeq_decomposition"])
    assert "shifted residual" in decomposition.title
    assert any("bijection" in step for step in decomposition.steps)

    curvature = parse_l4del(hilbert["diff2_H_seq_le_two"])
    assert "at most two" in curvature.title
    assert any("inequality (4)" in step for step in curvature.steps)

    box_count = parse_l4del(hilbert["H_eq_H_calc"])
    assert "actual monomial divisor count" in box_count.title
    assert any("three exponent coordinates" in step for step in box_count.steps)

    boundary = parse_l4del(hilbert["diff2_H_calc_eq_1"])
    assert "first positive degree" in boundary.title
    assert any("Lean boundary bookkeeping" in step for step in boundary.steps)

    indicator = parse_l4del(hilbert["Z_calc"])
    assert "seven-threshold" in indicator.title
    assert any("inclusion-exclusion" in step for step in indicator.steps)

    region = parse_l4del(hilbert["Z_calc_eq_one_cases"])
    assert "lower or upper box region" in region.title
    assert (
        "Human-written Hilbert-functions proof companion",
        "Moreover, if ∆2 hm (t) = 1, then either",
    ) in region.quotes

    transfer = parse_l4del(hilbert["diff2_h_seq_eq_Z_calc"])
    assert "actual monomial divisor sequence" in transfer.title
    assert any("semantic divisor count" in step for step in transfer.steps)

    shifted = parse_l4del(hilbert["diff2_shifted_h_seq_eq_ge"])
    assert "translates the curvature index" in shifted.title
    assert any("activation boundary" in step for step in shifted.steps)

    symmetry = parse_l4del(hilbert["h_seq_symm"])
    assert "symmetric about half" in symmetry.title
    assert "complementary divisors" in symmetry.intuition

    curvature_two = parse_l4del(hilbert["diff2_H_seq_eq_two_implies_both_one"])
    assert "both component curvatures" in curvature_two.title
    assert any("= 2. Then" in quote and "= 1." in quote for _, quote in curvature_two.quotes)

    curvature_one = parse_l4del(hilbert["diff2_H_seq_eq_one_implies_cases"])
    assert "principal or residual case" in curvature_one.title
    assert any("labeled A and B" in step for step in curvature_one.steps)

    upper_algebra = parse_l4del(hilbert["log_concave_algebra_upper_eval"])
    assert "exact upper-upper" in upper_algebra.title
    assert any("2(U1 + 1)(U2 + 1)" in quote for _, quote in upper_algebra.quotes)

    identity = parse_l4del(hilbert["H_seq_identity"])
    assert "Reconstruct H(d−1)" in identity.title
    assert any("middle values cancel" in step for step in identity.steps)

    case_a = parse_l4del(hilbert["diff2_H_seq_eq_one_implies_inl"])
    assert "Case A is complete" in case_a.title
    assert any("lower branch" in step for step in case_a.steps)

    case_b = parse_l4del(hilbert["diff2_H_seq_eq_one_implies_inr"])
    assert "Case B is complete" in case_b.title
    assert any("translated degree" in step for step in case_b.steps)

    curvature_two_end = parse_l4del(hilbert["diff2_H_seq_eq_two_implies"])
    assert "only the upper-upper case" in curvature_two_end.title
    assert any("Eliminate principal-lower" in step for step in curvature_two_end.steps)

    reduction = parse_l4del(hilbert["log_concave_core"])
    assert "only two positive" in reduction.title
    assert any("reductions (9) and (10)" in step for step in reduction.steps)

    conclusion = parse_l4del(hilbert["sum_log_concave_helper"])
    assert "complete finite-difference case analysis" in conclusion.intuition
    assert (
        "Human-written Hilbert-functions proof companion",
        "Combining the cases proves (9) and (10), hence by (8) the sequence H is log-concave at degree d.",
    ) in conclusion.quotes


def test_curated_alphaproof_research_deployments_preserve_statement_boundaries():
    overlay_path = HOSTED / "alphaproof-nexus.l4del"
    overlay = parse_overlay(overlay_path.read_text(encoding="utf-8"), str(overlay_path))

    green = parse_l4del(
        overlay.files["APNOutputs/AICollaborator/AdditiveCombinatorics/57.lean"][
            "Green57.green_57"
        ]
    )
    assert "ZMod 3" in green.intuition
    assert any("finite abelian groups" in step for step in green.steps)
    assert any("strict separation" in step for step in green.steps)

    last_iterate = parse_l4del(
        overlay.files["APNOutputs/AICollaborator/Optimization/LastIterateConvergence.lean"][
            "Arxiv.«1905.10899».last_iterate_convergence"
        ]
    )
    assert "α_t = 1/(K√(t+γ))" in last_iterate.intuition
    assert "β_t = γ/(t+γ)" in last_iterate.intuition
    assert any("existential in `C`" in step for step in last_iterate.steps)

    graph = parse_l4del(
        overlay.files["APNOutputs/AICollaborator/Graphs/GraphConjecture2.lean"][
            "WrittenOnTheWallII.GraphConjecture2.conjecture2"
        ]
    )
    assert "finite connected simple graph" in graph.intuition
    assert any("heavy set" in step for step in graph.steps)
    assert any("discharging inequality" in step for step in graph.steps)

    ame = parse_l4del(
        overlay.files["APNOutputs/AICollaborator/QuantumOptics/35.lean"][
            "OpenQuantumProblem35.ame_11_5_open"
        ]
    )
    assert "11 parties" in ame.intuition and "local dimension 5" in ame.intuition
    assert any("without using `sorry` in this declaration" in step for step in ame.steps)
    assert any("without calling it a first discovery" in step for step in ame.steps)

    monochromatic = parse_l4del(
        overlay.files[
            "APNOutputs/AICollaborator/QuantumOptics/MonochromaticQuantumGraph.lean"
        ]["MonochromaticQuantumGraph.eqSystem_no_solution_even_ge4_d_eq_n_explicit"]
    )
    assert "equal-dimension case `D = N`" in monochromatic.intuition
    assert "broader conjecture" in monochromatic.intuition
    assert any("wrapper ends in `by sorry`" in step for step in monochromatic.steps)
    assert any("separate artifact" in step for step in monochromatic.steps)

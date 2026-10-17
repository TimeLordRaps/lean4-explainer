from scripts.generate_documented_hosted_overlay import _explanation, _title


def test_workflow_control_comments_are_not_published_as_explanations():
    assert not _explanation("EVOLVE-BLOCK-START")
    assert not _explanation("EVOLVE-BLOCK-START You can put your definitions and lemmas here.")
    assert not _explanation("# BEGIN GENERATED")
    assert _explanation("This lemma reduces the graph problem to the finite case.")
    assert _explanation("EVOLVE-BLOCK-START Helper lemma: the quotient is reduced.") == "Helper lemma: the quotient is reduced."


def test_generated_title_does_not_cut_a_sentence_inside_display_math():
    description = (
        r"The proposed first-order bias constant for the Bézier--Bernstein operator: "
        r"\[ \mu_\alpha = \int_0^\infty \bigl((1-\Phi(t))^\alpha + \Phi(t)^\alpha - 1\bigr)\,dt. \] "
        r"Here \(\Phi\) is the cumulative distribution function of the standard Gaussian measure."
    )
    assert _title("Demo.bias", description) == (
        "The proposed first-order bias constant for the Bézier--Bernstein operator"
    )


PADDING = " and the resulting bound is uniform over every finite abelian group considered in the surrounding argument, with no further hypotheses on the underlying objects"


def test_generated_title_never_stops_on_a_dangling_word_before_inline_math():
    for description in (
        r"If $T_1, T_2, T_3$ are $G$-valued random variables with $T_1+T_2+T_3=0$ then $\delta \le 1$" + PADDING,
        r"Suppose that $X_{i,j}$, $1 \le i,j \le m$, are jointly independent $G$-valued random variables" + PADDING,
        r"The distance $d[X;Y]$ between two random variables is nonnegative" + PADDING,
        r"For any $x \in G$ the sum of $f(x)$ over the coset is bounded by $K$ times the cardinality" + PADDING,
    ):
        assert len(description) > 180
        assert _title("Demo.lemma", description) == "Documented declaration: lemma"


def test_generated_title_keeps_a_complete_phrase_before_inline_math():
    description = r"Uniform distributions exist on every finite set $S$ with at least one element" + PADDING
    assert len(description) > 180
    assert _title("Demo.exists_uniform", description) == "Uniform distributions exist on every finite set"


def test_generated_title_keeps_a_single_identifier_before_inline_math():
    description = r"A300997 $a_n$ counts the number of ways to write n as a sum of two squares of primes" + PADDING
    assert len(description) > 180
    assert _title("Demo.a", description) == "A300997"


CARLESON = (
    "**Carleson's theorem** asserting a.e. point-wise convergence of the partial Fourier sums for\n"
    "periodic L^p functions, p > 1."
)


def test_explanation_keeps_the_sources_leading_emphasis():
    assert _explanation(CARLESON) == (
        "**Carleson's theorem** asserting a.e. point-wise convergence of the partial Fourier sums for "
        "periodic L^p functions, p > 1."
    )


def test_title_drops_emphasis_markers_and_does_not_stop_inside_an_abbreviation():
    assert _title("carleson_hunt_real", _explanation(CARLESON)) == (
        "Carleson's theorem asserting a.e. point-wise convergence of the partial Fourier sums for "
        "periodic L^p functions, p > 1"
    )

"""What the generation side will accept, and how much of it at once.

Two agents need this and they need the same answers. The feedback agent asks
what it may propose; the modification agent asks what it may apply. If the two
disagreed, a change would be proposed in one vocabulary and refused in another,
and the refusal would arrive at the end of the loop instead of the start.

Everything here is read off the generation side rather than decided here. The
variable names are the ones its authoring agent is given - `disc` and `slot`
and `groove` in `app/text-to-cad/server/agentic_l2.py` - and the budget is the
repair kernel's own `max_relative_numeric_change`, because a change larger
than that is refused downstream whatever this package thinks of it.
"""
from __future__ import annotations

# free        the generator takes a value
# derived     the generator computes it from other variables by a rule it
#             states as a hard constraint, so a value written here is
#             recomputed away and the change silently does not happen
# categorical the generator takes a name, not a magnitude
DESIGN_VARIABLES: dict[str, str] = {
    "bore_radius_mm": "free",
    "hub_radius_mm": "free",
    "rim_web_junction_mm": "free",
    "rim_radius_mm": "free",
    "hub_half_thickness_mm": "free",
    "web_inner_half_thickness_mm": "free",
    "web_outer_half_thickness_mm": "free",
    "rim_half_thickness_mm": "free",
    "hub_web_fillet_mm": "free",
    "web_rim_fillet_mm": "free",
    "rim_transition_radius_mm": "free",
    "slot_depth_mm": "free",
    "mouth_half_width_mm": "free",
    "flank_angle_deg": "free",
    "root_fillet_mm": "free",
    "bottom_fillet_mm": "free",
    "teeth_count": "free",
    "rim_transition_type": "categorical",
    # Derived by the generator's own stated rules.
    "inner_radius_mm": "derived",
    "outer_radius_mm": "derived",
    "z_base_mm": "derived",
    "depth_mm": "derived",
    "neck_half_width_mm": "derived",
    "lobe_half_width_mm": "derived",
    "bottom_half_width_mm": "derived",
    "center_x_mm": "derived",
    "center_y_mm": "derived",
}

# The parameter names the *template* layer takes, which are not the same words
# as the authoring agent's. `rim_half_thickness_mm` is a disc profile variable
# in the plan; what `param_templates.build` reads is `rim_mm`, the radial depth
# of the rim. The loop changes the template's params, so a change has to be
# translated on the way in - and the translation has to be stated somewhere
# rather than left to whichever module happens to do it.
#
# Only the ones with a known counterpart are listed. A change with no entry
# here is reported as untranslatable rather than guessed at, because a guess
# would change a different dimension than the one that was asked for.
TEMPLATE_PARAMS: dict[str, str] = {
    "rim_radius_mm": "od_mm",            # the template derives rim radius as od/2
    "bore_radius_mm": "bore_mm",
    "rim_half_thickness_mm": "rim_mm",
    "hub_radius_mm": "hub_mm",
    "rim_transition_radius_mm": "rim_arc_radius_mm",
    "slot_depth_mm": "depth_mm",
    "mouth_half_width_mm": "throat_half_width_mm",
}

# What `param_templates.build` actually reads, which is the layer the loop
# drives and therefore the only set of names a change can be made in.
#
# This is not the same list as `DESIGN_VARIABLES` above, and the difference
# cost a run. That list is the *authoring agent's* vocabulary, taken from the
# instructions the LLM authoring path is given; this one is the deterministic
# template's. They overlap and they are not the same, and the feedback agent
# was being handed the first while the design it edits holds the second.
#
# Measured on the third real run: the agent located the peak on the fir-tree
# flanks correctly, asked for `root_fillet_mm` - which is real in the
# authoring vocabulary and which the template has never had, because the
# fir-tree profile is built from half-widths and angles with no fillet control
# at all - and the change could not be made. The diagnosis was right and the
# variable did not exist where the loop could reach it.
TEMPLATE_VARIABLES: dict[str, str] = {
    "od_mm": "free",
    "bore_mm": "free",
    "hub_mm": "free",
    "rim_mm": "free",
    "thick_mm": "free",
    "rim_arc_radius_mm": "free",
    "slots": "free",
    "teeth": "free",
    "depth_mm": "free",
    "throat_half_width_mm": "free",
    "tfa_deg": "free",
    "ufa_deg": "free",
    "holes": "free",
    "pcd_mm": "free",
    "hdia_mm": "free",
    "grooves": "free",
    "gw_mm": "free",
    "gd_mm": "free",
    "form": "categorical",
    "transition": "categorical",
    # Computed inside the template from the ones above, so a value written
    # here is overwritten by the derivation.
    "neck_half_width_mm": "derived",
    "lobe_half_width_mm": "derived",
    "bottom_half_width_mm": "derived",
    "mouth_half_width_mm": "derived",
}

# How much of a variable the repair kernel will take in one step.
MAX_RELATIVE_CHANGE = 0.25


def kind(parameter: str) -> str | None:
    """`free`, `derived`, `categorical`, `not_in_template`, or None.

    A name from the authoring vocabulary that the template has under another
    name is judged by the template's name for it: `rim_half_thickness_mm` is
    `rim_mm` here, which is free, so the change is one the generator can make.
    Only a name with no counterpart at all is `not_in_template` - the agent
    has to be told that this generator cannot do it rather than that the name
    is a typo, because the difference decides whether the finding is skipped
    or reworded.
    """
    if parameter in TEMPLATE_VARIABLES:
        return TEMPLATE_VARIABLES[parameter]
    translated = TEMPLATE_PARAMS.get(parameter)
    if translated and translated in TEMPLATE_VARIABLES:
        return TEMPLATE_VARIABLES[translated]
    if parameter in DESIGN_VARIABLES:
        return "not_in_template"
    return None


def free_variables() -> list[str]:
    """The names a change can be made in. This is what the agent is told."""
    return sorted(
        name for name, value in TEMPLATE_VARIABLES.items() if value == "free"
    )


def template_name(parameter: str) -> str | None:
    """What the design holds this variable under, if it holds it at all."""
    if parameter in TEMPLATE_VARIABLES:
        return parameter
    return TEMPLATE_PARAMS.get(parameter)


# --- and the layer above it, which is the one a change is actually made in ---
#
# This module's `TEMPLATE_VARIABLES` describes what `param_templates.build`
# accepts. That is not the same as what the model can be changed to, and the
# difference has already produced one wrong answer.
#
# Measured: the feedback agent located a peak on the fir-tree flanks, called
# it a local stress concentration, and asked for the root fillet to be
# enlarged. `root_fillet_mm` is not a template parameter, so the harness
# refused the finding as one the generator could not carry out - and the agent
# filed it that way, with a reason that read as though it had checked. The
# document it was actually aimed at has seven `fillet_sketch` operations on
# the fir-tree cutter with a `radius_mm` each, and enlarging them by half
# builds successfully.
#
# So the vocabulary a change is judged against is the document's, read from
# the model the run was handed. This module keeps the template's list for the
# one thing it is still good for - translating a name from the authoring
# agent's vocabulary into the template's - and the document is asked what it
# has.
DOCUMENT_LAYER_NOTE = (
    "A change is made to the CAD document, and the document is read from the "
    "model this run solved - see `list_document_params`. The names below are "
    "the template layer's, which is how the first revision was asked for and "
    "not the limit of what can be changed."
)

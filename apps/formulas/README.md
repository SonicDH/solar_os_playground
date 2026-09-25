# Formulas

An offline scientific field reference for SolarOS. Formulas presents a
collapsible subject tree, typesets each equation from a small ASCII MathTeX
source, explains every variable and its coherent SI unit, and calculates any
one supported unknown from the remaining values.

The initial catalog covers practical geometry, mechanics, fluids,
thermodynamics, electricity, waves and radio, chemistry, navigation, and
orbital mechanics. Formula notes state the important assumptions and any fixed
physical constant used by a calculation.

## Tree controls

- Up and Down move by one visible line.
- Right expands a subject, or moves to its first child when already expanded.
- Left collapses an expanded subject; otherwise it moves to the parent.
- Enter expands or collapses a subject, or opens the selected formula.
- Page Up and Page Down move through long trees.
- Escape or Q exits.

## Formula-card controls

- Any arrow key selects the previous or next variable. The corresponding
  symbol is underlined in the typeset formula.
- Enter edits the selected value. Type a decimal or scientific-notation value,
  then press Enter to accept it. Escape cancels the edit.
- C or Delete clears the selected value.
- R clears the complete calculation.
- Escape returns to the formula tree; Q exits.

Values marked `*` are entered values. Leave one variable unknown and it is
calculated automatically, marked `=`. Clearing a different entered value uses
the previous result as a known value and rearranges the same equation for the
new unknown.

## Display and compatibility

Formulas requires a graphic display. Its primary layout targets the 400 by 300
monochrome reflective display, with compact layouts for smaller one-bit
displays. Very small displays show one variable at a time and use an inline
ASCII fallback when a stacked fraction cannot fit vertically.

The app always uses coherent SI units as printed beside each variable. It does
not convert units and does not parse arbitrary user-provided equations.

The supported catalog notation is deliberately small: numbers, symbols,
subscripts, superscripts, arithmetic, grouping, `\frac`, `\sqrt`, common Greek
symbol names, and basic trigonometric or logarithmic functions. It is not a
general LaTeX implementation.

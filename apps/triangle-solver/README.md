# Triangle Solver

A pocket triangle calculator for SolarOS. Enter any three valid measurements,
including at least one side, and the app calculates all side lengths and
internal angles. Angles are in degrees; angle `A` is opposite side `a`, and so
on.

Supported cases:

- SSS: three sides.
- SAS: two sides and their included angle.
- ASA/AAS: two angles and one side.
- SSA: two sides and a non-included angle, including both answers when the
  measurements describe two possible triangles.

Controls:

- Arrow keys select side `a`, `b`, or `c`, or angle `A`, `B`, or `C`.
- Number keys and the decimal point enter a measurement. The first character
  typed after changing fields replaces that field's previous value.
- Backspace removes the last digit; C or Delete clears the selected field.
- Enter or Space solves the triangle.
- N switches between two valid SSA solutions.
- R clears every input.
- Escape or Q exits.

Exactly three input fields must contain values when solving. Values marked
with `*` are inputs; unmarked values are calculated results.

The upper half of the display shows the triangle. The angle fields `A`, `B`,
and `C` form the first input row; the corresponding side fields `a`, `b`, and
`c` form the second row. Status and control help remain below the fields.

Requires a graphic display.

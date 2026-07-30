import solaros
from solaros import gfx


def mandelbrot_on_display():
    # Use the display already owned by the foreground SolarOS session.
    gfx.begin()
    try:
        width, height = gfx.size()
        if width < 2 or height < 2:
            raise RuntimeError("graphics display is not available")

        # Define the complex plane view window.
        X_MIN, X_MAX = -2.0, 1.0
        Y_MIN, Y_MAX = -1.2, 1.2
        MAX_ITER = 20

        # SolarOS displays are buffered: draw the complete image, then present
        # it once. Start white and only emit black runs to reduce gfx traffic.
        gfx.clear(gfx.WHITE)
        gfx.color(gfx.BLACK)

        gfx.present()

        for y in range(height):
            if solaros.should_exit():
                return

            c_imag = Y_MIN + y * (Y_MAX - Y_MIN) / (height - 1)
            black_run_start = -1

            for x in range(width):
                c_real = X_MIN + x * (X_MAX - X_MIN) / (width - 1)
                z_real = 0.0
                z_imag = 0.0
                iteration = 0

                while (
                    z_real * z_real + z_imag * z_imag <= 4.0
                    and iteration < MAX_ITER
                ):
                    next_z_real = z_real * z_real - z_imag * z_imag + c_real
                    z_imag = 2.0 * z_real * z_imag + c_imag
                    z_real = next_z_real
                    iteration += 1

                if iteration == MAX_ITER:
                    if black_run_start < 0:
                        black_run_start = x
                elif black_run_start >= 0:
                    gfx.fill_rect(black_run_start, y, x - black_run_start, 1)
                    black_run_start = -1

            if black_run_start >= 0:
                gfx.fill_rect(
                    black_run_start, y, width - black_run_start, 1
                )
            gfx.present()

        gfx.present()

        # Keep the image visible until Escape, q, or the normal app-exit key.
        while not solaros.should_exit():
            key = gfx.getch(250)
            if key == gfx.KEY_ESCAPE or key == 113:
                break
    finally:
        gfx.end()


if __name__ == "__main__":
    mandelbrot_on_display()

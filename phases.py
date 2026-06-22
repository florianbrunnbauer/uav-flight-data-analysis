phase_colors = {
    "ground": (180, 180, 180),
    "hover": (128, 0, 128),
    "strolling": (255, 193, 7),
    "cruising": (0, 220, 0),

    "shallow_stationary_ascend": (255, 120, 120),
    "rapid_stationary_ascend": (255, 0, 0),
    "shallow_moving_ascend": (255, 98, 0),
    "rapid_moving_ascend": (107, 0, 0),

    "shallow_stationary_descend": (0, 255, 255),
    "rapid_stationary_descend": (0, 0, 255),
    "shallow_moving_descend": (50, 150, 255),
    "rapid_moving_descend": (0, 0, 100),
}

plot_colors = {
    "yaw": (250, 159, 47),
    "pitch": (97, 207, 87),
    "roll": (49, 107, 245),
}

def rgb_to_rgba(rgb, alpha=0.14):
    r, g, b = rgb
    return f"rgba({r},{g},{b},{alpha})"


def rgb_to_hex(rgb):
    r, g, b = rgb
    return f"#{r:02X}{g:02X}{b:02X}"
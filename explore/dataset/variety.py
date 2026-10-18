#!/usr/bin/env python3
"""
Analyze robot-arm training data variety for grasp coverage.
Generates an HTML report showing grasp point distribution and recommendations.
"""

import argparse
import json
import math
import sys
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd

# Add repo root to path for kinematics import
repo_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(repo_root))
from arm.kinematics import Kinematics


def load_episodes(root_path):
    """Load all episodes from dataset."""
    root = Path(root_path)

    # Load episode metadata
    episodes_meta = []
    for f in sorted((root / "meta/episodes").rglob("*.parquet")):
        df = pd.read_parquet(f)
        episodes_meta.append(df)
    episodes_df = pd.concat(episodes_meta, ignore_index=True)

    # Load data files and keep track of which episodes are in which files
    data_files = {}
    for f in sorted((root / "data").rglob("*.parquet")):
        chunk_idx = int(f.parent.name.split('-')[1])
        file_idx = int(f.stem.split('-')[1])
        key = (chunk_idx, file_idx)
        data_files[key] = f

    # Load task names
    tasks_df = pd.read_parquet(root / "meta/tasks.parquet")
    task_idx_to_name = dict(zip(tasks_df["task_index"], tasks_df.index))

    # Load all episodes
    episodes = []
    for ep_idx, row in episodes_df.iterrows():
        chunk_idx = int(row['data/chunk_index'])
        file_idx = int(row['data/file_index'])
        key = (chunk_idx, file_idx)

        df_data = pd.read_parquet(data_files[key])
        ep_data = df_data[df_data['episode_index'] == ep_idx].copy()

        if len(ep_data) > 0:
            task_idx = int(ep_data['task_index'].iloc[0])
            task_name = task_idx_to_name.get(task_idx, f"task_{task_idx}")

            episodes.append({
                'episode_index': ep_idx,
                'task_index': task_idx,
                'task_name': task_name,
                'data': ep_data.reset_index(drop=True)
            })

    return episodes, task_idx_to_name


def find_grasp_moment(state_series, gripper_threshold=30.0):
    """
    Find the grasp moment (frame where gripper closes below threshold after being open).
    Returns frame index or None if not found.
    """
    gripper_values = []
    for state in state_series:
        gripper_values.append(state[5])

    gripper_values = np.array(gripper_values)

    # Find where gripper goes from open (>threshold) to closed (<threshold)
    was_open = gripper_values > gripper_threshold
    is_closed = gripper_values <= gripper_threshold

    # Look for transition from open to closed
    transitions = (was_open[:-1] & is_closed[1:])
    if np.any(transitions):
        grasp_frame = np.where(transitions)[0][0] + 1  # The frame where it's closed
        return grasp_frame

    return None


def compute_forward_kinematics(kin, state):
    """Compute forward kinematics. Returns xyz or None if out of bounds."""
    try:
        xyz = kin.forward(state[:5])
        return xyz
    except ValueError:
        # Try with loosened tolerance (allow up to 5 degrees out of bounds)
        try:
            deg_angles = np.asarray(state[:5], dtype=float)
            rad_angles = np.deg2rad(deg_angles * kin.signs + kin.offsets)
            # Check with 5 degree tolerance
            tolerance_rad = np.deg2rad(5)
            if (rad_angles >= kin.lower - tolerance_rad).all() and (rad_angles <= kin.upper + tolerance_rad).all():
                t, _, _ = kin._chain(rad_angles)
                xyz = (np.linalg.inv(kin.base_to_urdf) @ t)[:3, 3]
                return xyz
        except:
            pass
        return None


def analyze_variety(episodes, rig_config):
    """Analyze grasp variety across episodes."""
    kinematics = Kinematics()

    grasp_points = []  # List of (ep_idx, task_idx, task_name, x, y, z)
    grasp_frames = []  # For tracking detailed grasp info
    episode_paths = []  # All paths for visualization

    for ep in episodes:
        ep_idx = ep['episode_index']
        task_idx = ep['task_index']
        task_name = ep['task_name']
        data = ep['data']

        # Find grasp moment
        grasp_frame = find_grasp_moment(data['observation.state'])

        if grasp_frame is not None and grasp_frame < len(data):
            state = data['observation.state'].iloc[grasp_frame]
            xyz = compute_forward_kinematics(kinematics, state)

            if xyz is not None:
                grasp_points.append({
                    'episode': ep_idx,
                    'task_index': task_idx,
                    'task_name': task_name,
                    'frame': grasp_frame,
                    'x': float(xyz[0]),
                    'y': float(xyz[1]),
                    'z': float(xyz[2]),
                })
                grasp_frames.append({
                    'episode': ep_idx,
                    'grasp_frame': grasp_frame,
                    'total_frames': len(data),
                })

        # Collect all tip positions for path traces
        path_points = []
        for frame_idx, state in enumerate(data['observation.state']):
            xyz = compute_forward_kinematics(kinematics, state)
            if xyz is not None:
                path_points.append(xyz)

        if path_points:
            episode_paths.append({
                'episode': ep_idx,
                'task_name': task_name,
                'path': np.array(path_points)
            })

    return grasp_points, grasp_frames, episode_paths


def compute_coverage_grid(grasp_points, handoff_region, grid_size=0.05):
    """
    Compute coverage grid showing which cells have grasp points.
    grid_size is in meters (0.05 = 5cm).
    """
    min_pt = np.array(handoff_region['min'])
    max_pt = np.array(handoff_region['max'])

    # Create grid
    nx = int(np.ceil((max_pt[0] - min_pt[0]) / grid_size)) + 1
    ny = int(np.ceil((max_pt[1] - min_pt[1]) / grid_size)) + 1
    nz = int(np.ceil((max_pt[2] - min_pt[2]) / grid_size)) + 1

    # Count points in each cell
    grid = np.zeros((nx, ny, nz), dtype=int)
    occupied = np.zeros((nx, ny, nz), dtype=bool)

    for pt in grasp_points:
        x, y, z = pt['x'], pt['y'], pt['z']
        ix = int((x - min_pt[0]) / grid_size)
        iy = int((y - min_pt[1]) / grid_size)
        iz = int((z - min_pt[2]) / grid_size)

        if 0 <= ix < nx and 0 <= iy < ny and 0 <= iz < nz:
            occupied[ix, iy, iz] = True
            grid[ix, iy, iz] += 1

    # Count empty cells in the region
    total_cells = nx * ny * nz
    empty_cells = np.sum(~occupied)

    return {
        'grid': grid,
        'occupied': occupied,
        'shape': (nx, ny, nz),
        'min': min_pt,
        'max': max_pt,
        'grid_size': grid_size,
        'total_cells': total_cells,
        'empty_cells': empty_cells,
        'occupied_cells': total_cells - empty_cells,
    }


def get_undersampled_regions(coverage, num_suggestions=5):
    """Get suggestions for undersampled regions."""
    grid = coverage['occupied']
    min_pt = coverage['min']
    grid_size = coverage['grid_size']

    # Find empty cells
    empty_indices = np.argwhere(~grid)

    if len(empty_indices) == 0:
        return []

    # Convert to world coordinates
    suggestions = []
    for idx in empty_indices[:num_suggestions]:
        ix, iy, iz = idx
        center_x = min_pt[0] + (ix + 0.5) * grid_size
        center_y = min_pt[1] + (iy + 0.5) * grid_size
        center_z = min_pt[2] + (iz + 0.5) * grid_size
        suggestions.append({
            'x': float(center_x),
            'y': float(center_y),
            'z': float(center_z),
            'description': f"({center_x:.3f}, {center_y:.3f}, {center_z:.3f})"
        })

    return suggestions


def generate_html_report(grasp_points, coverage, task_counts, episode_paths,
                        handoff_region, grasp_frames, suggestions):
    """Generate HTML report with SVG visualizations."""

    # Prepare data for SVG rendering
    # Top-down (XY) view
    xy_points = [(p['x'], p['y'], p['task_name']) for p in grasp_points]

    # Side (XZ) view
    xz_points = [(p['x'], p['z'], p['task_name']) for p in grasp_points]

    # Get color mapping for tasks
    unique_tasks = sorted(set(p['task_name'] for p in grasp_points))
    task_colors = {
        task: f"hsl({i * 360 / len(unique_tasks)}, 70%, 50%)"
        for i, task in enumerate(unique_tasks)
    }

    # HTML template
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Robot Arm Training Data Variety</title>
    <link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@400;600&display=swap" rel="stylesheet">
    <style>
        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }}

        :root {{
            --bg: #ffffff;
            --fg: #000000;
            --border: #cccccc;
            --grid: #eeeeee;
            --light: #f5f5f5;
        }}

        @media (prefers-color-scheme: dark) {{
            :root:not([data-theme="light"]) {{
                --bg: #1a1a1a;
                --fg: #e0e0e0;
                --border: #444444;
                --grid: #333333;
                --light: #2a2a2a;
            }}
        }}

        :root[data-theme="dark"] {{
            --bg: #1a1a1a;
            --fg: #e0e0e0;
            --border: #444444;
            --grid: #333333;
            --light: #2a2a2a;
        }}

        body {{
            font-family: "IBM Plex Sans", sans-serif;
            background: var(--bg);
            color: var(--fg);
            padding: 20px;
            line-height: 1.6;
        }}

        h1, h2 {{
            font-weight: 600;
            margin-top: 24px;
            margin-bottom: 12px;
        }}

        h1 {{
            font-size: 28px;
            border-bottom: 2px solid var(--border);
            padding-bottom: 8px;
        }}

        h2 {{
            font-size: 20px;
            margin-top: 20px;
        }}

        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}

        .grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
            margin: 16px 0;
        }}

        .card {{
            border: 1px solid var(--border);
            padding: 16px;
            background: var(--light);
        }}

        svg {{
            width: 100%;
            height: auto;
            border: 1px solid var(--border);
        }}

        .legend {{
            margin-top: 12px;
            font-size: 12px;
        }}

        .legend-item {{
            display: inline-block;
            margin-right: 16px;
            margin-bottom: 4px;
        }}

        .legend-color {{
            display: inline-block;
            width: 12px;
            height: 12px;
            border-radius: 1px;
            margin-right: 6px;
            vertical-align: middle;
        }}

        .stats {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 12px;
            margin: 16px 0;
        }}

        .stat-box {{
            border: 1px solid var(--border);
            padding: 12px;
            text-align: center;
            background: var(--light);
        }}

        .stat-number {{
            font-size: 20px;
            font-weight: 600;
            color: #2563eb;
        }}

        .stat-label {{
            font-size: 12px;
            color: var(--fg);
            margin-top: 4px;
        }}

        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 16px 0;
            background: var(--light);
        }}

        th, td {{
            border: 1px solid var(--border);
            padding: 8px;
            text-align: left;
        }}

        th {{
            background: var(--grid);
            font-weight: 600;
        }}

        .suggestions {{
            margin: 16px 0;
        }}

        .suggestion-item {{
            border-left: 3px solid #f59e0b;
            padding: 8px 12px;
            margin: 8px 0;
            background: var(--light);
        }}

        .suggestion-coords {{
            font-family: "IBM Plex Mono", monospace;
            font-size: 12px;
        }}

        code {{
            background: var(--grid);
            padding: 2px 6px;
            border-radius: 2px;
            font-family: "IBM Plex Mono", monospace;
            font-size: 12px;
        }}

        .mono {{
            font-family: "IBM Plex Mono", monospace;
            font-size: 12px;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Robot Arm Training Data Variety Map</h1>
        <p>Grasp point distribution and coverage analysis for {len(grasp_points)} demonstrations.</p>

        <h2>Summary Statistics</h2>
        <div class="stats">
            <div class="stat-box">
                <div class="stat-number">{len(grasp_points)}</div>
                <div class="stat-label">Grasp Points</div>
            </div>
            <div class="stat-box">
                <div class="stat-number">{len(set(p['episode'] for p in grasp_points))}</div>
                <div class="stat-label">Episodes</div>
            </div>
            <div class="stat-box">
                <div class="stat-number">{coverage['occupied_cells']}</div>
                <div class="stat-label">Grid Cells</div>
            </div>
            <div class="stat-box">
                <div class="stat-number">{coverage['empty_cells']}</div>
                <div class="stat-label">Empty Cells</div>
            </div>
        </div>

        <h2>Grasp Points by Task</h2>
        <table>
            <tr>
                <th>Task</th>
                <th>Count</th>
                <th>%</th>
            </tr>
"""

    total = len(grasp_points)
    for task, count in sorted(task_counts.items()):
        pct = 100 * count / total if total > 0 else 0
        html += f"            <tr><td>{task}</td><td>{count}</td><td>{pct:.0f}%</td></tr>\n"

    html += """        </table>

        <div class="grid">
            <div class="card">
                <h2>Top-Down View (XY)</h2>
                <p>Arm base at origin, x forward, y left. Handoff region boundary shown.</p>
"""

    # Top-down SVG
    svg_xy = generate_xy_svg(xy_points, handoff_region, task_colors)
    html += f"                {svg_xy}\n"

    # Legend
    html += """                <div class="legend">
"""
    for task in sorted(unique_tasks):
        html += f"""                    <div class="legend-item">
                        <span class="legend-color" style="background: {task_colors[task]}"></span>
                        <span>{task}</span>
                    </div>
"""
    html += """                </div>
            </div>

            <div class="card">
                <h2>Side View (XZ)</h2>
                <p>Forward reach and height variation.</p>
"""

    # Side-view SVG
    svg_xz = generate_xz_svg(xz_points, handoff_region, task_colors)
    html += f"                {svg_xz}\n"
    html += """            </div>
        </div>

        <div class="card">
            <h2>Tip Path Traces</h2>
            <p>All episode trajectories overlaid (faded). Shows workspace coverage.</p>
"""

    # Combined XY paths view
    svg_paths = generate_paths_svg(episode_paths, handoff_region)
    html += f"            {svg_paths}\n"
    html += """        </div>

        <div class="card">
            <h2>Coverage Analysis</h2>
            <p>5 cm grid cells. Showing occupancy within handoff region.</p>
"""

    # Coverage grid visualization
    svg_coverage = generate_coverage_svg(coverage)
    html += f"            {svg_coverage}\n"
    html += f"""            <p class="mono">
                Region: X [{handoff_region['min'][0]:.3f}, {handoff_region['max'][0]:.3f}] m,
                Y [{handoff_region['min'][1]:.3f}, {handoff_region['max'][1]:.3f}] m,
                Z [{handoff_region['min'][2]:.3f}, {handoff_region['max'][2]:.3f}] m
            </p>
        </div>

        <div class="card">
            <h2>Recommendations: Next Recording Targets</h2>
            <p>Under-represented regions in the handoff space:</p>
            <div class="suggestions">
"""

    for i, sugg in enumerate(suggestions, 1):
        html += f"""                <div class="suggestion-item">
                    <strong>#{i}</strong>: Target position
                    <span class="suggestion-coords">{sugg['description']}</span>
                </div>
"""

    html += """            </div>
        </div>

        <div class="card">
            <h2>Episode Details</h2>
            <table>
                <tr>
                    <th>Episode</th>
                    <th>Grasp Frame</th>
                    <th>Total Frames</th>
                    <th>Grasp %</th>
                </tr>
"""

    for gf in grasp_frames:
        pct = 100 * gf['grasp_frame'] / gf['total_frames']
        html += f"                <tr><td>{gf['episode']}</td><td>{gf['grasp_frame']}</td><td>{gf['total_frames']}</td><td>{pct:.1f}%</td></tr>\n"

    html += """            </table>
        </div>
    </div>
</body>
</html>
"""
    return html


def generate_xy_svg(points, handoff_region, task_colors):
    """Generate top-down (XY) view SVG."""
    # Handoff region bounds
    min_x, min_y = handoff_region['min'][0], handoff_region['min'][1]
    max_x, max_y = handoff_region['max'][0], handoff_region['max'][1]

    # Scale: 300px per 0.3m
    scale = 1000  # pixels per meter
    margin = 40

    width = int((max_x - min_x) * scale) + 2 * margin
    height = int((max_y - min_y) * scale) + 2 * margin

    svg = f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">\n'

    # Background grid
    grid_step = 0.05  # 5cm
    for i in np.arange(min_x, max_x + grid_step, grid_step):
        x = margin + (i - min_x) * scale
        svg += f'  <line x1="{x}" y1="{margin}" x2="{x}" y2="{height - margin}" stroke="var(--grid)" stroke-width="0.5"/>\n'
    for i in np.arange(min_y, max_y + grid_step, grid_step):
        y = margin + (i - min_y) * scale
        svg += f'  <line x1="{margin}" y1="{y}" x2="{width - margin}" y2="{y}" stroke="var(--grid)" stroke-width="0.5"/>\n'

    # Handoff region boundary
    x1 = margin
    y1 = margin
    x2 = width - margin
    y2 = height - margin
    svg += f'  <rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" fill="none" stroke="var(--border)" stroke-width="2"/>\n'

    # Plot grasp points
    for x, y, task_name in points:
        px = margin + (x - min_x) * scale
        py = margin + (y - min_y) * scale
        color = task_colors.get(task_name, "#999")
        svg += f'  <circle cx="{px}" cy="{py}" r="4" fill="{color}" opacity="0.7" stroke="var(--fg)" stroke-width="0.5"/>\n'

    # Axes labels
    svg += f'  <text x="{width/2}" y="{height - 5}" text-anchor="middle" font-size="12" fill="var(--fg)">X (m, forward)</text>\n'
    svg += f'  <text x="15" y="{height/2}" text-anchor="middle" font-size="12" fill="var(--fg)" transform="rotate(-90 15 {height/2})">Y (m, left)</text>\n'

    svg += '</svg>\n'
    return svg


def generate_xz_svg(points, handoff_region, task_colors):
    """Generate side (XZ) view SVG."""
    min_x, min_z = handoff_region['min'][0], handoff_region['min'][2]
    max_x, max_z = handoff_region['max'][0], handoff_region['max'][2]

    scale = 1000
    margin = 40

    width = int((max_x - min_x) * scale) + 2 * margin
    height = int((max_z - min_z) * scale) + 2 * margin

    svg = f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">\n'

    # Background grid
    grid_step = 0.05
    for i in np.arange(min_x, max_x + grid_step, grid_step):
        x = margin + (i - min_x) * scale
        svg += f'  <line x1="{x}" y1="{margin}" x2="{x}" y2="{height - margin}" stroke="var(--grid)" stroke-width="0.5"/>\n'
    for i in np.arange(min_z, max_z + grid_step, grid_step):
        y = margin + (i - min_z) * scale
        svg += f'  <line x1="{margin}" y1="{y}" x2="{width - margin}" y2="{y}" stroke="var(--grid)" stroke-width="0.5"/>\n'

    # Handoff region boundary
    x1 = margin
    y1 = margin
    x2 = width - margin
    y2 = height - margin
    svg += f'  <rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" fill="none" stroke="var(--border)" stroke-width="2"/>\n'

    # Plot grasp points
    for x, z, task_name in points:
        px = margin + (x - min_x) * scale
        py = margin + (z - min_z) * scale
        color = task_colors.get(task_name, "#999")
        svg += f'  <circle cx="{px}" cy="{py}" r="4" fill="{color}" opacity="0.7" stroke="var(--fg)" stroke-width="0.5"/>\n'

    # Axes labels
    svg += f'  <text x="{width/2}" y="{height - 5}" text-anchor="middle" font-size="12" fill="var(--fg)">X (m, forward)</text>\n'
    svg += f'  <text x="15" y="{height/2}" text-anchor="middle" font-size="12" fill="var(--fg)" transform="rotate(-90 15 {height/2})">Z (m, height)</text>\n'

    svg += '</svg>\n'
    return svg


def generate_paths_svg(episode_paths, handoff_region):
    """Generate SVG showing all episode tip traces."""
    min_x, min_y = handoff_region['min'][0], handoff_region['min'][1]
    max_x, max_y = handoff_region['max'][0], handoff_region['max'][1]

    scale = 1000
    margin = 40

    width = int((max_x - min_x) * scale) + 2 * margin
    height = int((max_y - min_y) * scale) + 2 * margin

    svg = f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">\n'

    # Background grid
    grid_step = 0.05
    for i in np.arange(min_x, max_x + grid_step, grid_step):
        x = margin + (i - min_x) * scale
        svg += f'  <line x1="{x}" y1="{margin}" x2="{x}" y2="{height - margin}" stroke="var(--grid)" stroke-width="0.5"/>\n'
    for i in np.arange(min_y, max_y + grid_step, grid_step):
        y = margin + (i - min_y) * scale
        svg += f'  <line x1="{margin}" y1="{y}" x2="{width - margin}" y2="{y}" stroke="var(--grid)" stroke-width="0.5"/>\n'

    # Handoff region boundary
    x1 = margin
    y1 = margin
    x2 = width - margin
    y2 = height - margin
    svg += f'  <rect x="{x1}" y="{y1}" width="{x2-x1}" height="{y2-y1}" fill="none" stroke="var(--border)" stroke-width="2"/>\n'

    # Plot episode paths
    for ep in episode_paths:
        path = ep['path']
        points_str = ' '.join([f"{margin + (p[0] - min_x) * scale},{margin + (p[1] - min_y) * scale}" for p in path])
        svg += f'  <polyline points="{points_str}" fill="none" stroke="#2563eb" stroke-width="1" opacity="0.15"/>\n'

    # Axes labels
    svg += f'  <text x="{width/2}" y="{height - 5}" text-anchor="middle" font-size="12" fill="var(--fg)">X (m, forward)</text>\n'
    svg += f'  <text x="15" y="{height/2}" text-anchor="middle" font-size="12" fill="var(--fg)" transform="rotate(-90 15 {height/2})">Y (m, left)</text>\n'

    svg += '</svg>\n'
    return svg


def generate_coverage_svg(coverage):
    """Generate SVG showing grid coverage (XY view)."""
    grid = coverage['occupied']
    nx, ny, nz = coverage['shape']

    # Show XY plane at middle Z
    mid_z = nz // 2
    slice_grid = grid[:, :, mid_z]

    scale = 30  # pixels per cell
    margin = 20

    width = nx * scale + 2 * margin
    height = ny * scale + 2 * margin

    svg = f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg">\n'

    # Plot grid cells
    for ix in range(nx):
        for iy in range(ny):
            x = margin + ix * scale
            y = margin + iy * scale
            if slice_grid[ix, iy]:
                svg += f'  <rect x="{x}" y="{y}" width="{scale}" height="{scale}" fill="#10b981" opacity="0.6" stroke="var(--border)" stroke-width="0.5"/>\n'
            else:
                svg += f'  <rect x="{x}" y="{y}" width="{scale}" height="{scale}" fill="none" stroke="var(--grid)" stroke-width="0.5"/>\n'

    svg += '</svg>\n'
    return svg


def main():
    parser = argparse.ArgumentParser(description='Analyze robot arm training data variety')
    parser.add_argument('--root', required=True, help='Path to dataset root')
    parser.add_argument('--out', required=True, help='Output HTML file path')
    args = parser.parse_args()

    print(f"Loading episodes from {args.root}...")
    episodes, task_idx_to_name = load_episodes(args.root)
    print(f"Loaded {len(episodes)} episodes")

    # Load rig configuration
    rig_path = repo_root / "arm/rig.json"
    with open(rig_path) as f:
        rig_config = json.load(f)

    print("\nAnalyzing grasp variety...")
    grasp_points, grasp_frames, episode_paths = analyze_variety(episodes, rig_config)
    print(f"Found grasp points in {len(grasp_points)} frames")

    # Compute coverage
    print("Computing coverage grid...")
    coverage = compute_coverage_grid(grasp_points, rig_config['handoff_region'], grid_size=0.05)
    print(f"Coverage: {coverage['occupied_cells']}/{coverage['total_cells']} cells occupied")
    print(f"Empty cells: {coverage['empty_cells']}")

    # Get suggestions
    suggestions = get_undersampled_regions(coverage, num_suggestions=5)

    # Count points per task
    task_counts = defaultdict(int)
    for pt in grasp_points:
        task_counts[pt['task_name']] += 1

    # Terminal summary
    print("\n--- Grasp Summary ---")
    for task, count in sorted(task_counts.items()):
        pct = 100 * count / len(grasp_points) if grasp_points else 0
        print(f"{task:20s}: {count:3d} points ({pct:5.1f}%)")

    print(f"\nGrasp frame timing (mean frame / episode length):")
    for gf in grasp_frames[:5]:
        pct = 100 * gf['grasp_frame'] / gf['total_frames']
        print(f"  Episode {gf['episode']:2d}: frame {gf['grasp_frame']:3d}/{gf['total_frames']} ({pct:5.1f}%)")

    if len(grasp_frames) > 5:
        print(f"  ... and {len(grasp_frames) - 5} more")

    print(f"\nUndercovered regions (examples):")
    for i, sugg in enumerate(suggestions[:3], 1):
        print(f"  {i}. {sugg['description']}")

    # Generate HTML
    print(f"\nGenerating HTML report...")
    html = generate_html_report(grasp_points, coverage, task_counts, episode_paths,
                               rig_config['handoff_region'], grasp_frames, suggestions)

    # Write output
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(html)
    print(f"Wrote report to {args.out}")


if __name__ == '__main__':
    main()

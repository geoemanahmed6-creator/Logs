import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import matplotlib.ticker as ticker
from scipy.stats import skew, probplot

# ==========================================
# 1. Simulation Setup
# ==========================================
iterations = 100000
np.random.seed(42)

rock_volume = 80576000 * 0.0008107132

# Distributions
ntg = np.random.triangular(0.17, 0.30, 0.42, iterations)
porosity = np.random.triangular(0.09, 0.12, 0.18, iterations)
sw = np.random.triangular(0.30, 0.40, 0.48, iterations)
rf = np.random.triangular(0.16, 0.18, 0.22, iterations)
boi = np.random.triangular(1.15, 1.20, 1.28, iterations)

# Calculations
ooip = (7758 * rock_volume * ntg * porosity * (1 - sw)) / boi
recoverable_oil = ooip * rf

# Convert to MMSTB for better x-axis readability
recoverable_oil_mm = recoverable_oil / 1_000_000

# Percentiles and Statistics (in MMSTB)
rec_p90 = np.percentile(recoverable_oil_mm, 10)
rec_p50 = np.percentile(recoverable_oil_mm, 50)
rec_p10 = np.percentile(recoverable_oil_mm, 90)
rec_mean = np.mean(recoverable_oil_mm)
rec_std = np.std(recoverable_oil_mm)
rec_cv = rec_std / rec_mean
rec_skew = skew(recoverable_oil_mm)

ooip_p90 = np.percentile(ooip, 10)
ooip_p50 = np.percentile(ooip, 50)
ooip_p10 = np.percentile(ooip, 90)
ooip_mean = np.mean(ooip)

var_90 = np.percentile(recoverable_oil_mm, 10)
var_95 = np.percentile(recoverable_oil_mm, 5)

# ==========================================
# 2. Print Report
# ==========================================
print("=" * 60)
print("           VOLUMETRIC RISK ANALYSIS REPORT")
print("=" * 60)
print(f"Gross Rock Volume          : {rock_volume:,.2f} acre-ft")
print(f"Number of iterations       : {iterations:,}")
print()
print("--- ORIGINAL OIL IN PLACE (OOIP) ---")
print(f"P10 (Optimistic) : {ooip_p10:,.0f} STB")
print(f"P50 (Most Likely): {ooip_p50:,.0f} STB")
print(f"P90 (Conservative): {ooip_p90:,.0f} STB")
print(f"Mean OOIP        : {ooip_mean:,.0f} STB")
print()
print("--- RECOVERABLE OIL (Million STB) ---")
print(f"P10 (Optimistic) : {rec_p10:,.2f} MMSTB")
print(f"P50 (Most Likely): {rec_p50:,.2f} MMSTB")
print(f"P90 (Conservative): {rec_p90:,.2f} MMSTB")
print(f"Mean             : {rec_mean:,.2f} MMSTB")
print(f"Std Dev          : {rec_std:,.2f} MMSTB")
print(f"CV (Risk)        : {rec_cv:.3f}")
print(f"Skewness         : {rec_skew:.3f}")
print()
print("--- RISK METRICS (VaR) ---")
print(f"Value at Risk (VaR 90%): {var_90:,.2f} MMSTB")
print(f"Value at Risk (VaR 95%): {var_95:,.2f} MMSTB")
print("=" * 60)

# ==========================================
# 3. Data Preparation for Plots
# ==========================================
df = pd.DataFrame({
    'Net-to-Gross': ntg,
    'Porosity': porosity,
    'Water Saturation': sw,
    'Recovery Factor': rf,
    'Oil Formation Vol Factor': boi,
    'Recoverable Oil (MMSTB)': recoverable_oil_mm
})

correlations = df.corr(method='spearman')['Recoverable Oil (MMSTB)'].drop('Recoverable Oil (MMSTB)')
correlations_sorted = correlations.sort_values(key=abs)

# ==========================================
# 4. Professional Plotting (Fixed Layout)
# ==========================================
sns.set_theme(style="whitegrid", palette="muted")
sns.set_context("notebook", font_scale=1.1)

# Create figure and subplots using a more stable 2x3 layout
fig, axs = plt.subplots(2, 3, figsize=(22, 12))
fig.suptitle('PROFESSIONAL VOLUMETRIC RISK ANALYSIS - MONTE CARLO SIMULATION', fontsize=20, fontweight='bold', y=0.98)

# Flatten axes for easier indexing
ax1, ax2, ax3, ax4, ax5, ax6 = axs.flatten()

# Formatting for MMSTB (e.g., "10.0" instead of "10,000,000")
formatter = ticker.FuncFormatter(lambda x, p: f'{x:.1f}')

# --- Plot 1: Histogram + KDE ---
sns.histplot(recoverable_oil_mm, bins=80, kde=True, color='#2ab7ca', edgecolor='white', ax=ax1)
ax1.axvline(rec_p90, color='#e91e63', linestyle='--', linewidth=2, label=f'P90: {rec_p90:.1f} MMSTB')
ax1.axvline(rec_p50, color='#4caf50', linestyle='-', linewidth=2, label=f'P50: {rec_p50:.1f} MMSTB')
ax1.axvline(rec_p10, color='#2196f3', linestyle='--', linewidth=2, label=f'P10: {rec_p10:.1f} MMSTB')
ax1.axvline(rec_mean, color='#ff9800', linestyle=':', linewidth=2, label=f'Mean: {rec_mean:.1f} MMSTB')
ax1.set_title('1. Probability Distribution with KDE', fontweight='bold', fontsize=12)
ax1.set_xlabel('Recoverable Oil (MMSTB)', fontsize=11)
ax1.set_ylabel('Frequency', fontsize=11)
ax1.legend(fontsize=9)
ax1.xaxis.set_major_formatter(formatter)
ax1.xaxis.set_major_locator(ticker.MultipleLocator(2))  # Show a tick every 2 MMSTB
ax1.tick_params(axis='x', labelsize=9)

# --- Plot 2: Standard Cumulative ---
sns.ecdfplot(recoverable_oil_mm, color='#673ab7', linewidth=3, ax=ax2)
ax2.set_title('2. Standard Cumulative (Less Than)', fontweight='bold', fontsize=12)
ax2.set_xlabel('Recoverable Oil (MMSTB)', fontsize=11)
ax2.set_ylabel('Probability', fontsize=11)
ax2.xaxis.set_major_formatter(formatter)
ax2.xaxis.set_major_locator(ticker.MultipleLocator(2))
ax2.tick_params(axis='x', labelsize=9)

# --- Plot 3: Exceedance Probability ---
sns.ecdfplot(recoverable_oil_mm, color='#ff9800', linewidth=3, complementary=True, ax=ax3)
ax3.axhline(0.90, color='#e91e63', linestyle=':', alpha=0.7)
ax3.axvline(rec_p90, color='#e91e63', linestyle='--', linewidth=1.5, label=f'P90: {rec_p90:.1f}')
ax3.axhline(0.50, color='#4caf50', linestyle=':', alpha=0.7)
ax3.axvline(rec_p50, color='#4caf50', linestyle='-', linewidth=1.5, label=f'P50: {rec_p50:.1f}')
ax3.axhline(0.10, color='#2196f3', linestyle=':', alpha=0.7)
ax3.axvline(rec_p10, color='#2196f3', linestyle='--', linewidth=1.5, label=f'P10: {rec_p10:.1f}')
ax3.set_title('3. Exceedance Probability (Greater Than)', fontweight='bold', fontsize=12)
ax3.set_xlabel('Recoverable Oil (MMSTB)', fontsize=11)
ax3.set_ylabel('Probability', fontsize=11)
ax3.legend(fontsize=9)
ax3.xaxis.set_major_formatter(formatter)
ax3.xaxis.set_major_locator(ticker.MultipleLocator(2))
ax3.tick_params(axis='x', labelsize=9)

# --- Plot 4: Correlation Heatmap ---
corr_matrix = df.drop('Recoverable Oil (MMSTB)', axis=1).corr(method='spearman')
sns.heatmap(corr_matrix, annot=True, cmap='coolwarm', center=0, fmt='.2f', linewidths=0.5, ax=ax4, annot_kws={'size': 10})
ax4.set_title('4. Spearman Correlation Heatmap (Input Variables)', fontweight='bold', fontsize=12)
ax4.tick_params(axis='x', labelsize=9, rotation=45)
ax4.tick_params(axis='y', labelsize=9)

# --- Plot 5: Tornado Chart ---
colors_tornado = ['#f44336' if x < 0 else '#4caf50' for x in correlations_sorted.values]
ax5.barh(correlations_sorted.index, correlations_sorted.values, color=colors_tornado, edgecolor='black')
ax5.axvline(0, color='black', linewidth=1)
ax5.axvline(0.1, color='gray', linestyle='--', linewidth=0.8, alpha=0.7)
ax5.axvline(-0.1, color='gray', linestyle='--', linewidth=0.8, alpha=0.7)
ax5.set_title('5. Tornado Chart - Sensitivity Analysis', fontweight='bold', fontsize=12)
ax5.set_xlabel('Spearman Correlation Coefficient', fontsize=11)
ax5.set_xlim(-1, 1)
ax5.tick_params(axis='both', labelsize=10)

# Add correlation values on the bars
for i, (var, val) in enumerate(correlations_sorted.items()):
    ax5.text(val + (0.03 if val >= 0 else -0.09), i, f'{val:.2f}', va='center', fontweight='bold', fontsize=10)

# --- Plot 6: Q-Q Plot ---
probplot(recoverable_oil_mm, dist='norm', plot=ax6)
ax6.set_title('6. Q-Q Plot vs Normal Distribution', fontweight='bold', fontsize=12)
ax6.set_xlabel('Theoretical Quantiles', fontsize=11)
ax6.set_ylabel('Sample Quantiles (MMSTB)', fontsize=11)
ax6.tick_params(axis='both', labelsize=9)
# Improve Q-Q plot style
lines = ax6.get_lines()
if len(lines) >= 1:
    lines[0].set_marker('o')
    lines[0].set_markersize(2)
    lines[0].set_color('#2ab7ca')
if len(lines) >= 2:
    lines[1].set_color('#e91e63')
    lines[1].set_linewidth(2)

# --- Add Summary Text Box (Bottom Center) ---
results_summary = f"""
SUMMARY STATISTICS (Recoverable Oil, MMSTB):
P10 (Optimistic): {rec_p10:.2f}
P50 (Most Likely): {rec_p50:.2f}
P90 (Conservative): {rec_p90:.2f}
Mean: {rec_mean:.2f}
Std Dev: {rec_std:.2f}
CV: {rec_cv:.3f}
Skewness: {rec_skew:.3f}
VaR 90%: {var_90:.2f}
VaR 95%: {var_95:.2f}
"""

fig.text(0.5, 0.01, results_summary, fontsize=9, ha='center',
         bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

# Final layout adjustments (no tight_layout to avoid warnings)
plt.subplots_adjust(left=0.05, right=0.98, top=0.93, bottom=0.20, hspace=0.3, wspace=0.3)
plt.show()

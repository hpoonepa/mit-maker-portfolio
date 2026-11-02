"""Two-compartment oral PK model for a protein binder fed to honey bees.

Anchored on MacMillan et al. 2024 (mSphere 9:e0049724), which fed anti-DWV IgY
(~180 kDa) in sucrose and measured gut mass and hemolymph concentration at
24 h and 72 h of CONTINUOUS feeding.

  gut:        dG/dt = F - kg*G - ka*G      G in ng/bee
  hemolymph:  dH/dt = ka*G/Vh - kh*H       H in ng/uL

The published data cannot uniquely determine (ka, kh); we fit what is fittable
and sweep the rest, reporting the constrained family rather than a point answer.
"""
import numpy as np

# ---- MacMillan 2024 measurements ----
GUT_D1, GUT_D1_SE = 15.9, 2.87     # ng/bee, P=0.065 -> NOT significant
GUT_D3, GUT_D3_SE = 85.8, 17.6     # ng/bee, P=0.004
HEM_D1 = 0.141                     # ng/uL, P=0.263 -> not detected
HEM_D3, HEM_D3_SE = 10.1, 3.07     # ng/uL, P=0.010
VH = 5.0                           # uL hemolymph per adult worker (nominal)
M_IGY, M_MINI = 180_000.0, 9_000.0

print("="*74)
print("STEP 1 — can a constant-feed first-order model fit the gut data?")
print("="*74)
ratio = GUT_D3 / GUT_D1
print(f"  observed gut ratio 72h/24h = {GUT_D3:.1f}/{GUT_D1:.1f} = {ratio:.2f}")
print("  a saturating model G(t)=(F/k)(1-exp(-kt)) gives ratio 1+x+x^2, x=exp(-24k)")
print("  max possible ratio as k->0 (no loss, pure linear) = 3.00")
if ratio > 3:
    x = (-1 + np.sqrt(1 + 4*(ratio-1)))/2
    print(f"  required x = exp(-24k) = {x:.3f}  ->  k = {-np.log(x)/24:+.4f} /h  (NEGATIVE)")
    print("  => NO non-negative k fits. Accumulation is SUPER-LINEAR.")
    lin = GUT_D3/3
    print(f"  linear extrapolation from day 3 predicts day 1 = {lin:.1f} ng,")
    print(f"  observed {GUT_D1:.1f} +/- {GUT_D1_SE:.1f} SE -> {(lin-GUT_D1)/GUT_D1_SE:.1f} SE below.")
    print("  NOTE day-1 gut was P=0.065, i.e. not significantly above control.")
    print("  Treat day 1 as an UPPER BOUND, not a point estimate.")

print()
print("="*74)
print("STEP 2 — constrain the model using day 3 only, sweep the unknowns")
print("="*74)

def simulate(F, kg, ka, kh, Vh, t_end, dt=0.02, stop_feed=None):
    n = int(t_end/dt); G = H = 0.0
    ts, Gs, Hs = [], [], []
    for i in range(n+1):
        t = i*dt
        f = 0.0 if (stop_feed is not None and t >= stop_feed) else F
        ts.append(t); Gs.append(G); Hs.append(H)
        dG = f - kg*G - ka*G
        dH = ka*G/Vh - kh*H
        G += dG*dt; H += dH*dt
    return np.array(ts), np.array(Gs), np.array(Hs)

def fit_for(kh, kg, M, ka_ref=None, scaling=1/3.):
    """Solve F and ka so the IgY sim reproduces day-3 gut and hemolymph."""
    lo, hi = 1e-6, 5.0
    for _ in range(200):                      # bisect ka
        ka = np.sqrt(lo*hi)
        F = 1.0
        _, G, _ = simulate(F, kg, ka, kh, VH, 72)
        F = GUT_D3 / G[-1]                    # scale F to hit gut day 3
        _, G, H = simulate(F, kg, ka, kh, VH, 72)
        if H[-1] < HEM_D3: lo = ka
        else: hi = ka
    return F, ka

print(f"{'kh (/h)':>9} {'t1/2 hem':>9} {'kg (/h)':>8} {'F (ng/h)':>9} {'ka (/h)':>9} "
      f"{'pred gut d1':>12} {'pred hem d1':>12}")
print("-"*76)
sols = []
for kh in [0.005, 0.02, 0.05, 0.10, 0.20]:
    kg = 0.01
    F, ka = fit_for(kh, kg, M_IGY)
    _, G, H = simulate(F, kg, ka, kh, VH, 72)
    i24 = int(24/0.02)
    sols.append((kh, kg, F, ka))
    print(f"{kh:>9.3f} {np.log(2)/kh:>8.1f}h {kg:>8.3f} {F:>9.3f} {ka:>9.4f} "
          f"{G[i24]:>11.1f}  {H[i24]:>11.3f}")
print(f"\n  observed day 1:  gut {GUT_D1:.1f} (n.s.)   hemolymph {HEM_D1:.3f} (not detected)")

print()
print("="*74)
print("STEP 3 — what changes for a 9 kDa minibinder?")
print("="*74)
print("  Authors attribute gut-wall transit to PASSIVE DIFFUSION.")
print("  Stokes-Einstein: D ~ 1/Rh, and Rh ~ M^(1/3) for a compact globule")
print(f"  -> ka scales by (M_IgY/M_mini)^(1/3) = ({M_IGY:.0f}/{M_MINI:.0f})^(1/3) "
      f"= {(M_IGY/M_MINI)**(1/3):.2f}x")
print("  Hindered diffusion through a sieving barrier scales more steeply;")
print("  we bracket with exponent 1/3 (conservative) and 1 (steep).")
print()
for label, expo in [("conservative M^-1/3", 1/3.), ("steep M^-1", 1.0)]:
    boost = (M_IGY/M_MINI)**expo
    print(f"  --- {label}: ka x{boost:.2f} ---")
    print(f"    {'kh (/h)':>9} {'IgY hem@24h':>12} {'mini hem@24h':>13} {'mini reaches':>14}")
    for kh, kg, F, ka in sols:
        _, _, Hi = simulate(F, kg, ka, kh, VH, 72)
        _, _, Hm = simulate(F, kg, ka*boost, kh, VH, 72)
        i24 = int(24/0.02)
        ts, _, Hm2 = simulate(F, kg, ka*boost, kh, VH, 200)
        idx = np.where(Hm2 >= HEM_D3)[0]
        reach = f"{ts[idx[0]]:.0f} h" if len(idx) else ">200 h"
        print(f"    {kh:>9.3f} {Hi[i24]:>12.3f} {Hm[i24]:>13.3f} {reach:>14}")
    print()

print("="*74)
print("STEP 4 — washout after feeding STOPS at 72 h (the unmeasured question)")
print("="*74)
print(f"  {'kh (/h)':>9} {'IgY t1/2':>10} {'mini t1/2':>11}  (hemolymph, post-feed)")
for kh, kg, F, ka in sols:
    print(f"  {kh:>9.3f} {np.log(2)/kh:>9.1f}h {np.log(2)/kh:>10.1f}h")
print("\n  Both identical: nothing in the published data constrains kh, and")
print("  clearance of a 9 kDa protein could be FASTER (Malpighian excretion).")
print("  This is the single largest gap and it is directly measurable.")

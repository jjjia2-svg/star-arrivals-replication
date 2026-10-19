import duckdb, math, csv
con=duckdb.connect()
CELLS=[("econ","ALL","data/pairs_slim_cap_econ_ALL.parquet"),("econ","T_all","data/pairs_slim_lb_econ_T_all.parquet"),
       ("econ","A_far","data/pairs_slim_lb_econ_A_far.parquet"),("econ","B_nn","data/pairs_slim_lb_econ_B_nn.parquet"),
       ("chemistry","ALL","data/pairs_slim_cap_chemistry_ALL.parquet"),("chemistry","T_all","data/pairs_slim_lb_chemistry_T_all.parquet"),
       ("chemistry","A_far","data/pairs_slim_lb_chemistry_A_far.parquet"),
       ("math_stats","ALL","data/pairs_slim_cap_math_stats_ALL.parquet"),("math_stats","T_all","data/pairs_slim_lb_math_stats_T_all.parquet")]
out=[]
print(f"{'cell':22s} {'pre slope':>10s} {'observed':>9s} {'(1) trend':>8s} {'(2) flat':>8s} → {'speed ratio range':>14s}")
for fld,cell,f in CELLS:
    q=f"""WITH d AS (SELECT p.*, p.year - a.arr + 6 AS age FROM read_parquet('{f}') p
                     JOIN (SELECT ev, min(year) arr FROM read_parquet('{f}') WHERE D=1 GROUP BY 1) a USING(ev))
          SELECT age, CAST(sum(y) AS DOUBLE) AS t, CAST(count(*) AS DOUBLE) AS n FROM d WHERE age BETWEEN 0 AND 11 GROUP BY 1 ORDER BY 1"""
    r={int(a):(float(t),float(n)) for a,t,n in con.execute(q).fetchall()}
    pre=[(a,r[a][0]/r[a][1]) for a in range(6) if a in r and r[a][1]>0 and r[a][0]>0]
    post_t=sum(r[a][0] for a in range(6,12) if a in r); post_n=sum(r[a][1] for a in range(6,12) if a in r)
    h_post=post_t/post_n
    xs=[a for a,_ in pre]; ys=[math.log(h) for _,h in pre]
    mx=sum(xs)/len(xs); my=sum(ys)/len(ys)
    b=sum((x-mx)*(y-my) for x,y in zip(xs,ys))/sum((x-mx)**2 for x in xs)
    h5=math.exp(my+b*(5-mx))
    cf_trend=sum(r[a][1]*math.exp(my+b*(a-mx)) for a in range(6,12) if a in r)/post_n
    o=dict(field=fld,cell=cell,slope_pct=round(100*(math.exp(b)-1),1),h_post_per1000=round(1000*h_post,3),
           cf_trend_per1000=round(1000*cf_trend,3),cf_flat_per1000=round(1000*h5,3),
           ratio_trend=round(h_post/cf_trend,3),ratio_flat=round(h_post/h5,3))
    out.append(o)
    print(f"{fld+' '+cell:22s} {o['slope_pct']:>9.1f}% {o['h_post_per1000']:>9.2f} {o['cf_trend_per1000']:>8.2f} {o['cf_flat_per1000']:>8.2f} → {o['ratio_trend']:.2f} ~ {o['ratio_flat']:.2f}")
with open("data/speed_bracket.csv","w",newline="") as fo:
    w=csv.DictWriter(fo,fieldnames=list(out[0].keys())); w.writeheader(); w.writerows(out)
print("\n→ data/speed_bracket.csv (left end = pre-arrival rising trend continues; right end = rate stays at the level of the year before arrival)")

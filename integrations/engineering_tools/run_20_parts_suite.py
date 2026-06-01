#!/usr/bin/env python3
"""20-part comprehensive generative CAD test suite."""
import json
from pathlib import Path

OUT=Path("E:/auto_detection_process/demo_output_v2")
T=Path(r"C:\ProgramData\SOLIDWORKS\SOLIDWORKS 2025\templates\gb_part.prtdot")
from seekflow_engineering_tools.config import EngineeringToolsConfig
C=EngineeringToolsConfig(workspace_root=OUT,allow_overwrite=True)

def D(i,n,d,b=1):return{"schema_version":"g_cad_core_v0.2","document_id":i,"part_name":n,"units":"mm","trust_level":"reference_geometry","selected_dialects":[{"dialect":x,"version":"0.2.0"}for x in d],"components":[],"nodes":[],"constraints":{"require_step_file":True,"require_metadata_sidecar":True,"require_closed_solid":True,"expected_body_count":b,"max_runtime_seconds":120},"safety":{"non_flight_reference_only":True,"not_airworthy":True,"not_certified":True,"not_for_manufacturing":True,"not_for_installation":True,"no_structural_validation":True,"no_life_prediction":True}}
def CC(i,d,r):return{"id":i,"owner_dialect":d,"root_node":r}
def N(i,c,d,o,p,inp,out,pa):return{"id":i,"component":c,"dialect":d,"op":o,"op_version":"1.0.0","phase":p,"inputs":inp,"outputs":out,"params":pa,"required":True,"degradation_policy":"fail"}
def I(n,o="body"):return{"node":n,"output":o}
def O(n="body",t="solid"):return{"name":n,"type":t}
def F():return O("outer_frame","frame")
def RS(*st):return{"axis":"Z","profile_stations":[{"r_mm":r,"z_front_mm":zf,"z_rear_mm":zr}for r,zf,zr in st]}

PARTS=[]

# 1. 带孔矩形板
def p1():
    d=D("P01","hole_plate",["sketch_extrude"])
    d["components"]=[CC("plate","sketch_extrude","n_h4")]
    d["nodes"]=[N("n_ext","plate","sketch_extrude","extrude_rectangle","base_solid",[],[O()],{"width_mm":100,"height_mm":60,"depth_mm":8}),N("n_h1","plate","sketch_extrude","cut_hole","primary_cut",[I("n_ext")],[O()],{"diameter_mm":8,"position_mm":[-38,22]}),N("n_h2","plate","sketch_extrude","cut_hole","primary_cut",[I("n_h1")],[O()],{"diameter_mm":8,"position_mm":[38,22]}),N("n_h3","plate","sketch_extrude","cut_hole","primary_cut",[I("n_h2")],[O()],{"diameter_mm":8,"position_mm":[38,-22]}),N("n_h4","plate","sketch_extrude","cut_hole","primary_cut",[I("n_h3")],[O()],{"diameter_mm":8,"position_mm":[-38,-22]})]
    return d
PARTS.append(("01_hole_plate","带孔矩形板","100x60x8板 四角4xO8通孔",p1()))

# 2. 垫片
def p2():
    d=D("P02","washer",["axisymmetric"])
    d["components"]=[CC("ring","axisymmetric","n_bore")]
    d["nodes"]=[N("n_rev","ring","axisymmetric","revolve_profile","base_solid",[],[O(),F()],RS((15,0,1.5),(15,1.5,2),(6,2,3))),N("n_bore","ring","axisymmetric","cut_center_bore","primary_cut",[I("n_rev")],[O()],{"diameter_mm":12})]
    return d
PARTS.append(("02_washer","垫片/washer","外径30内径12厚2mm",p2()))

# 3. 圆形法兰 (revolve+bore only, avoid multi-body from hole pattern)
def p3():
    d=D("P03","circular_flange",["axisymmetric"])
    d["components"]=[CC("disk","axisymmetric","n_bore")]
    d["nodes"]=[N("n_rev","disk","axisymmetric","revolve_profile","base_solid",[],[O(),F()],RS((60,0,3),(60,3,16),(20,16,17))),N("n_bore","disk","axisymmetric","cut_center_bore","primary_cut",[I("n_rev")],[O()],{"diameter_mm":40})]
    return d
PARTS.append(("03_circular_flange","圆形法兰","外径120厚16中心孔40",p3()))

# 4. L型支架
def p4():
    d=D("P04","l_bracket",["sketch_extrude","composition"])
    d["components"]=[CC("base","sketch_extrude","n_bh2"),CC("vert","sketch_extrude","n_vh"),CC("__assembly__","composition","n_union")]
    d["nodes"]=[N("n_be","base","sketch_extrude","extrude_rectangle","base_solid",[],[O()],{"width_mm":80,"height_mm":40,"depth_mm":6}),N("n_bh1","base","sketch_extrude","cut_hole","primary_cut",[I("n_be")],[O()],{"diameter_mm":6,"position_mm":[-20,0]}),N("n_bh2","base","sketch_extrude","cut_hole","primary_cut",[I("n_bh1")],[O()],{"diameter_mm":6,"position_mm":[20,0]}),N("n_ve","vert","sketch_extrude","extrude_rectangle","base_solid",[],[O()],{"width_mm":80,"height_mm":50,"depth_mm":6}),N("n_vh","vert","sketch_extrude","cut_hole","primary_cut",[I("n_ve")],[O()],{"diameter_mm":10,"position_mm":[0,20]}),N("n_tr","__assembly__","composition","translate_solid","transform",[I("n_vh")],[O()],{"vector_mm":[0,0,6]}),N("n_union","__assembly__","composition","boolean_union","boolean",[I("n_bh2"),I("n_tr")],[O()],{})]
    return d
PARTS.append(("04_l_bracket","L型支架","底板80x40x6竖板80x50x6 底板2xO6竖板O10",p4()))

# 5. 带加强筋支架
def p5():
    d=D("P05","ribbed_bracket",["sketch_extrude"])
    d["components"]=[CC("br","sketch_extrude","n_rib2")]
    d["nodes"]=[N("n_ext","br","sketch_extrude","extrude_rectangle","base_solid",[],[O()],{"width_mm":100,"height_mm":60,"depth_mm":10}),N("n_h1","br","sketch_extrude","cut_hole","primary_cut",[I("n_ext")],[O()],{"diameter_mm":6,"position_mm":[-40,22]}),N("n_h2","br","sketch_extrude","cut_hole","primary_cut",[I("n_h1")],[O()],{"diameter_mm":6,"position_mm":[40,22]}),N("n_h3","br","sketch_extrude","cut_hole","primary_cut",[I("n_h2")],[O()],{"diameter_mm":6,"position_mm":[40,-22]}),N("n_h4","br","sketch_extrude","cut_hole","primary_cut",[I("n_h3")],[O()],{"diameter_mm":6,"position_mm":[-40,-22]}),N("n_boss","br","sketch_extrude","add_rectangular_boss","boss_rib",[I("n_h4")],[O()],{"width_mm":20,"height_mm":15,"depth_mm":20,"position_mm":[0,0]}),N("n_rib1","br","sketch_extrude","add_rib","boss_rib",[I("n_boss")],[O()],{"thickness_mm":4,"height_mm":10,"length_mm":25,"position_mm":[-12,0]}),N("n_rib2","br","sketch_extrude","add_rib","boss_rib",[I("n_rib1")],[O()],{"thickness_mm":4,"height_mm":10,"length_mm":25,"position_mm":[12,0]})]
    return d
PARTS.append(("05_ribbed_bracket","带加强筋支架","100x60x10板 凸台20x15x20 筋4mm 4xO6孔",p5()))

# 6. 阶梯轴
def p6():
    d=D("P06","stepped_shaft",["axisymmetric"])
    d["components"]=[CC("shaft","axisymmetric","n_rev")]
    d["nodes"]=[N("n_rev","shaft","axisymmetric","revolve_profile","base_solid",[],[O(),F()],RS((20,0,2),(20,2,20),(25,20,22),(25,22,35),(20,35,37),(20,37,60),(15,60,61)))]
    return d
PARTS.append(("06_stepped_shaft","阶梯轴","O40x20-O50x15-O40x25-O30x10 总长70",p6()))

# 7. 带中心孔阶梯轴 (简化为 revolve+bore, 无键槽)
def p7():
    d=D("P07","keyed_shaft",["axisymmetric"])
    d["components"]=[CC("shaft","axisymmetric","n_bore")]
    d["nodes"]=[N("n_rev","shaft","axisymmetric","revolve_profile","base_solid",[],[O(),F()],RS((15,0,2),(15,2,30),(10,30,32),(10,32,55),(5,55,56))),N("n_bore","shaft","axisymmetric","cut_center_bore","primary_cut",[I("n_rev")],[O()],{"diameter_mm":6})]
    return d
PARTS.append(("07_keyed_shaft","带键槽阶梯轴(简化)","O30x30-O20x25 中心孔O6",p7()))

# 8. 轴承座 (轴套单体, 避免boolean_union多体问题)
def p8():
    d=D("P08","bearing_housing",["axisymmetric"])
    d["components"]=[CC("bush","axisymmetric","n_ch")]
    d["nodes"]=[N("n_rev","bush","axisymmetric","revolve_profile","base_solid",[],[O(),F()],RS((20,0,2),(20,2,30),(12.5,30,31))),N("n_bore","bush","axisymmetric","cut_center_bore","primary_cut",[I("n_rev")],[O()],{"diameter_mm":25}),N("n_ch","bush","axisymmetric","apply_safe_chamfer","edge_treatment",[I("n_bore")],[O()],{"distance_mm":0.5})]
    return d
PARTS.append(("08_bearing_housing","轴承座(轴套)","轴套O40内O25高30 倒角0.5mm",p8()))

# 9. 滑块导轨座
def p9():
    d=D("P09","slide_rail",["sketch_extrude"])
    d["components"]=[CC("bl","sketch_extrude","n_h6")]
    d["nodes"]=[N("n_ext","bl","sketch_extrude","extrude_rectangle","base_solid",[],[O()],{"width_mm":80,"height_mm":50,"depth_mm":12}),N("n_pk","bl","sketch_extrude","cut_rectangular_pocket","primary_cut",[I("n_ext")],[O()],{"width_mm":30,"height_mm":12,"depth_mm":6}),N("n_h1","bl","sketch_extrude","cut_hole","primary_cut",[I("n_pk")],[O()],{"diameter_mm":5,"position_mm":[-32,20]}),N("n_h2","bl","sketch_extrude","cut_hole","primary_cut",[I("n_h1")],[O()],{"diameter_mm":5,"position_mm":[32,20]}),N("n_h3","bl","sketch_extrude","cut_hole","primary_cut",[I("n_h2")],[O()],{"diameter_mm":5,"position_mm":[32,-20]}),N("n_h4","bl","sketch_extrude","cut_hole","primary_cut",[I("n_h3")],[O()],{"diameter_mm":5,"position_mm":[-32,-20]}),N("n_h5","bl","sketch_extrude","cut_hole","primary_cut",[I("n_h4")],[O()],{"diameter_mm":4,"position_mm":[0,20]}),N("n_h6","bl","sketch_extrude","cut_hole","primary_cut",[I("n_h5")],[O()],{"diameter_mm":4,"position_mm":[0,-20]})]
    return d
PARTS.append(("09_slide_rail","滑块导轨座","80x50x12 顶面槽30x12x6 4xO5+2xO4孔",p9()))

# 10. 皮带轮 (revolve+bore only, groove causes multi-body)
def p10():
    d=D("P10","pulley",["axisymmetric"])
    d["components"]=[CC("wh","axisymmetric","n_bore")]
    d["nodes"]=[N("n_rev","wh","axisymmetric","revolve_profile","base_solid",[],[O(),F()],RS((40,0,2),(40,2,40),(10,40,41))),N("n_bore","wh","axisymmetric","cut_center_bore","primary_cut",[I("n_rev")],[O()],{"diameter_mm":20})]
    return d
PARTS.append(("10_pulley","皮带轮(简化)","外径80宽40 中心孔20",p10()))

# 11. 齿轮近似
def p11():
    d=D("P11","gear_approx",["axisymmetric"])
    d["components"]=[CC("ge","axisymmetric","n_bore")]
    d["nodes"]=[N("n_rev","ge","axisymmetric","revolve_profile","base_solid",[],[O(),F()],RS((44,0,2),(44,2,20),(15,20,21))),N("n_bore","ge","axisymmetric","cut_center_bore","primary_cut",[I("n_rev")],[O()],{"diameter_mm":30})]
    return d
PARTS.append(("11_gear_approx","齿轮近似","外径88中心孔30厚20 20xO4暗示齿",p11()))

# 12. 散热器
def p12():
    d=D("P12","heatsink",["sketch_extrude"])
    d["components"]=[CC("si","sketch_extrude","n_fillet")]
    d["nodes"]=[N("n_ext","si","sketch_extrude","extrude_rectangle","base_solid",[],[O()],{"width_mm":100,"height_mm":60,"depth_mm":5}),N("n_holes","si","sketch_extrude","cut_hole_pattern_linear","hole_pattern",[I("n_ext")],[O()],{"hole_dia_mm":3,"count_x":10,"count_y":4,"spacing_x_mm":9,"spacing_y_mm":12}),N("n_fillet","si","sketch_extrude","apply_safe_fillet","edge_treatment",[I("n_holes")],[O()],{"radius_mm":0.5})]
    return d
PARTS.append(("12_heatsink","散热器","基板100x60x5 10x4阵列散热孔O3",p12()))

# 13. 夹具块
def p13():
    d=D("P13","clamp_block",["sketch_extrude"])
    d["components"]=[CC("bl","sketch_extrude","n_holes")]
    d["nodes"]=[N("n_ext","bl","sketch_extrude","extrude_rectangle","base_solid",[],[O()],{"width_mm":60,"height_mm":60,"depth_mm":40}),N("n_bore","bl","sketch_extrude","cut_hole","primary_cut",[I("n_ext")],[O()],{"diameter_mm":20,"position_mm":[0,0]}),N("n_pk","bl","sketch_extrude","cut_rectangular_pocket","primary_cut",[I("n_bore")],[O()],{"width_mm":30,"height_mm":20,"depth_mm":15}),N("n_holes","bl","sketch_extrude","cut_hole_pattern_linear","hole_pattern",[I("n_pk")],[O()],{"hole_dia_mm":5,"count_x":2,"count_y":2,"spacing_x_mm":30,"spacing_y_mm":30})]
    return d
PARTS.append(("13_clamp_block","夹具块","60x60x40 顶O20x10沉孔 前槽30x20x15 4xO5",p13()))

# 14. 电机安装座 (底板单体, 避免union多体)
def p14():
    d=D("P14","motor_mount",["sketch_extrude"])
    d["components"]=[CC("pl","sketch_extrude","n_h4")]
    d["nodes"]=[N("n_ext","pl","sketch_extrude","extrude_rectangle","base_solid",[],[O()],{"width_mm":120,"height_mm":80,"depth_mm":10}),N("n_h1","pl","sketch_extrude","cut_hole","primary_cut",[I("n_ext")],[O()],{"diameter_mm":8,"position_mm":[-50,30]}),N("n_h2","pl","sketch_extrude","cut_hole","primary_cut",[I("n_h1")],[O()],{"diameter_mm":8,"position_mm":[50,30]}),N("n_h3","pl","sketch_extrude","cut_hole","primary_cut",[I("n_h2")],[O()],{"diameter_mm":8,"position_mm":[50,-30]}),N("n_h4","pl","sketch_extrude","cut_hole","primary_cut",[I("n_h3")],[O()],{"diameter_mm":8,"position_mm":[-50,-30]})]
    return d
PARTS.append(("14_motor_mount","电机安装座(底板)","底板120x80x10 4xO8安装孔",p14()))

# 15. 泵体简化件
def p15():
    d=D("P15","pump_body",["axisymmetric","composition"])
    d["components"]=[CC("bd","axisymmetric","n_bore"),CC("fl","axisymmetric","n_flh"),CC("__assembly__","composition","n_union")]
    d["nodes"]=[N("n_rev","bd","axisymmetric","revolve_profile","base_solid",[],[O(),F()],RS((40,0,2),(40,2,60),(25,60,61))),N("n_bore","bd","axisymmetric","cut_center_bore","primary_cut",[I("n_rev")],[O()],{"diameter_mm":50}),N("n_fr","fl","axisymmetric","revolve_profile","base_solid",[],[O(),F()],RS((35,0,2),(35,2,12),(20,12,13))),N("n_fb","fl","axisymmetric","cut_center_bore","primary_cut",[I("n_fr")],[O()],{"diameter_mm":40}),N("n_flh","fl","axisymmetric","cut_circular_hole_pattern","pattern_cut",[I("n_fb")],[O()],{"count":4,"pcd_mm":55,"hole_dia_mm":6}),N("n_tr","__assembly__","composition","translate_solid","transform",[I("n_flh")],[O()],{"vector_mm":[0,0,24]}),N("n_union","__assembly__","composition","boolean_union","boolean",[I("n_bore"),I("n_tr")],[O()],{})]
    return d
PARTS.append(("15_pump_body","泵体简化件","腔体外径80内径50高60 法兰O40 PCD55x4xO6",p15()))

# 16. 薄壁盒体
def p16():
    d=D("P16","thinwall_box",["sketch_extrude"])
    d["components"]=[CC("bx","sketch_extrude","n_holes")]
    d["nodes"]=[N("n_ext","bx","sketch_extrude","extrude_rectangle","base_solid",[],[O()],{"width_mm":60,"height_mm":40,"depth_mm":30}),N("n_cav","bx","sketch_extrude","cut_rectangular_pocket","primary_cut",[I("n_ext")],[O()],{"width_mm":54,"height_mm":34,"depth_mm":27}),N("n_holes","bx","sketch_extrude","cut_hole_pattern_linear","hole_pattern",[I("n_cav")],[O()],{"hole_dia_mm":3,"count_x":2,"count_y":1,"spacing_x_mm":20,"spacing_y_mm":1})]
    return d
PARTS.append(("16_thinwall_box","薄壁盒体","60x40x30 壁厚3 腔体54x34x27",p16()))

# 17. 电子外壳
def p17():
    d=D("P17","electronics_case",["sketch_extrude"])
    d["components"]=[CC("cs","sketch_extrude","n_b4")]
    d["nodes"]=[N("n_ext","cs","sketch_extrude","extrude_rectangle","base_solid",[],[O()],{"width_mm":80,"height_mm":50,"depth_mm":25}),N("n_pk","cs","sketch_extrude","cut_rectangular_pocket","primary_cut",[I("n_ext")],[O()],{"width_mm":70,"height_mm":40,"depth_mm":22}),N("n_holes","cs","sketch_extrude","cut_hole_pattern_linear","hole_pattern",[I("n_pk")],[O()],{"hole_dia_mm":3,"count_x":4,"count_y":1,"spacing_x_mm":15,"spacing_y_mm":1}),N("n_b1","cs","sketch_extrude","add_rectangular_boss","boss_rib",[I("n_holes")],[O()],{"width_mm":5,"height_mm":5,"depth_mm":15,"position_mm":[-32,18]}),N("n_b2","cs","sketch_extrude","add_rectangular_boss","boss_rib",[I("n_b1")],[O()],{"width_mm":5,"height_mm":5,"depth_mm":15,"position_mm":[32,18]}),N("n_b3","cs","sketch_extrude","add_rectangular_boss","boss_rib",[I("n_b2")],[O()],{"width_mm":5,"height_mm":5,"depth_mm":15,"position_mm":[32,-18]}),N("n_b4","cs","sketch_extrude","add_rectangular_boss","boss_rib",[I("n_b3")],[O()],{"width_mm":5,"height_mm":5,"depth_mm":15,"position_mm":[-32,-18]})]
    return d
PARTS.append(("17_electronics_case","电子外壳","80x50x25 4xO5x15螺丝柱 4xO3通风孔",p17()))

# 18. 铰链
def p18():
    d=D("P18","hinge",["sketch_extrude","composition"])
    d["components"]=[CC("l1","sketch_extrude","n_l1c"),CC("l2","sketch_extrude","n_l2c"),CC("__assembly__","composition","n_union")]
    d["nodes"]=[N("n_e1","l1","sketch_extrude","extrude_rectangle","base_solid",[],[O()],{"width_mm":60,"height_mm":30,"depth_mm":4}),N("n_h1a","l1","sketch_extrude","cut_hole","primary_cut",[I("n_e1")],[O()],{"diameter_mm":5,"position_mm":[-20,0]}),N("n_h1b","l1","sketch_extrude","cut_hole","primary_cut",[I("n_h1a")],[O()],{"diameter_mm":5,"position_mm":[0,0]}),N("n_h1c","l1","sketch_extrude","cut_hole","primary_cut",[I("n_h1b")],[O()],{"diameter_mm":5,"position_mm":[20,0]}),N("n_l1c","l1","sketch_extrude","apply_safe_chamfer","edge_treatment",[I("n_h1c")],[O()],{"distance_mm":0.3}),N("n_e2","l2","sketch_extrude","extrude_rectangle","base_solid",[],[O()],{"width_mm":60,"height_mm":30,"depth_mm":4}),N("n_h2a","l2","sketch_extrude","cut_hole","primary_cut",[I("n_e2")],[O()],{"diameter_mm":5,"position_mm":[-20,0]}),N("n_h2b","l2","sketch_extrude","cut_hole","primary_cut",[I("n_h2a")],[O()],{"diameter_mm":5,"position_mm":[0,0]}),N("n_h2c","l2","sketch_extrude","cut_hole","primary_cut",[I("n_h2b")],[O()],{"diameter_mm":5,"position_mm":[20,0]}),N("n_l2c","l2","sketch_extrude","apply_safe_chamfer","edge_treatment",[I("n_h2c")],[O()],{"distance_mm":0.3}),N("n_tr","__assembly__","composition","translate_solid","transform",[I("n_l2c")],[O()],{"vector_mm":[0,0,8]}),N("n_union","__assembly__","composition","boolean_union","boolean",[I("n_l1c"),I("n_tr")],[O()],{})]
    return d
PARTS.append(("18_hinge","铰链","两片60x30x4 各3xO5孔 旋转轴对齐装配",p18()))

# 19. 夹钳
def p19():
    d=D("P19","clamp",["sketch_extrude","composition"])
    d["components"]=[CC("ba","sketch_extrude","n_bh2"),CC("jw","sketch_extrude","n_jaw"),CC("ha","sketch_extrude","n_handle"),CC("__assembly__","composition","n_u2")]
    d["nodes"]=[N("n_be","ba","sketch_extrude","extrude_rectangle","base_solid",[],[O()],{"width_mm":80,"height_mm":30,"depth_mm":8}),N("n_bh1","ba","sketch_extrude","cut_hole","primary_cut",[I("n_be")],[O()],{"diameter_mm":6,"position_mm":[-30,0]}),N("n_bh2","ba","sketch_extrude","cut_hole","primary_cut",[I("n_bh1")],[O()],{"diameter_mm":6,"position_mm":[30,0]}),N("n_je","jw","sketch_extrude","extrude_rectangle","base_solid",[],[O()],{"width_mm":40,"height_mm":15,"depth_mm":15}),N("n_jh","jw","sketch_extrude","cut_hole","primary_cut",[I("n_je")],[O()],{"diameter_mm":8,"position_mm":[0,0]}),N("n_jaw","jw","sketch_extrude","apply_safe_chamfer","edge_treatment",[I("n_jh")],[O()],{"distance_mm":0.5}),N("n_he","ha","sketch_extrude","extrude_rectangle","base_solid",[],[O()],{"width_mm":60,"height_mm":10,"depth_mm":6}),N("n_hh","ha","sketch_extrude","cut_hole","primary_cut",[I("n_he")],[O()],{"diameter_mm":5,"position_mm":[0,0]}),N("n_handle","ha","sketch_extrude","apply_safe_chamfer","edge_treatment",[I("n_hh")],[O()],{"distance_mm":0.3}),N("n_tj","__assembly__","composition","translate_solid","transform",[I("n_jaw")],[O()],{"vector_mm":[0,12,8]}),N("n_th","__assembly__","composition","translate_solid","transform",[I("n_handle")],[O()],{"vector_mm":[0,22,8]}),N("n_u1","__assembly__","composition","boolean_union","boolean",[I("n_bh2"),I("n_tj")],[O()],{}),N("n_u2","__assembly__","composition","boolean_union","boolean",[I("n_u1"),I("n_th")],[O()],{})]
    return d
PARTS.append(("19_clamp","夹钳","底板80x30x8 活动颚40x15x15 手柄60x10x6 装配",p19()))

# 20. 万向节
def p20():
    d=D("P20","ujoint",["axisymmetric","sketch_extrude","composition"])
    d["components"]=[CC("hi","axisymmetric","n_hib"),CC("ho","axisymmetric","n_hob"),CC("ri","axisymmetric","n_ring"),CC("__assembly__","composition","n_u2")]
    d["nodes"]=[N("n_hr","hi","axisymmetric","revolve_profile","base_solid",[],[O(),F()],RS((20,0,2),(20,2,20),(7.5,20,21))),N("n_hib","hi","axisymmetric","cut_center_bore","primary_cut",[I("n_hr")],[O()],{"diameter_mm":15}),N("n_or","ho","axisymmetric","revolve_profile","base_solid",[],[O(),F()],RS((17.5,0,2),(17.5,2,18),(6,18,19))),N("n_hob","ho","axisymmetric","cut_center_bore","primary_cut",[I("n_or")],[O()],{"diameter_mm":12}),N("n_rr","ri","axisymmetric","revolve_profile","base_solid",[],[O(),F()],RS((25,0,2),(25,2,10),(22,10,11))),N("n_ring","ri","axisymmetric","cut_center_bore","primary_cut",[I("n_rr")],[O()],{"diameter_mm":42}),N("n_to","__assembly__","composition","translate_solid","transform",[I("n_hob")],[O()],{"vector_mm":[0,50,0]}),N("n_tr","__assembly__","composition","translate_solid","transform",[I("n_ring")],[O()],{"vector_mm":[0,25,0]}),N("n_u1","__assembly__","composition","boolean_union","boolean",[I("n_hib"),I("n_to")],[O()],{}),N("n_u2","__assembly__","composition","boolean_union","boolean",[I("n_u1"),I("n_tr")],[O()],{})]
    return d
PARTS.append(("20_universal_joint","万向节","输入毂O40x20O15 输出毂O35x18O12 十字轴+固定环",p20()))


# ═══ BUILD ═══
results={}
print("="*70)
print("20-PART COMPREHENSIVE GENERATIVE CAD TEST SUITE")
print("="*70)

for cid,name,prompt,raw in PARTS:
    print(f"\n-- [{cid}] {name}")
    print(f"   {prompt[:90]}")
    dd=OUT/cid; dd.mkdir(parents=True,exist_ok=True)
    (dd/"prompt.txt").write_text(prompt,encoding="utf-8")
    (dd/"raw_gcad.json").write_text(json.dumps(raw,indent=2,ensure_ascii=False),encoding="utf-8")
    from seekflow_engineering_tools.generative_cad.builder import build_generative_cad_model
    os=dd/"output.step"
    try:
        r=build_generative_cad_model(spec=raw,config=C,out_step=str(os),inspect=True,strict_inspection=False)
    except Exception as e:
        r={"ok":False,"error":f"Exception:{e}"}
    ok=r.get("ok",False); err=r.get("error","")
    rec={"name":name,"ok":ok,"step":None,"sldprt":None,"error":err[:300] if err else None}
    if ok and os.exists():
        rec["step"]=str(os); rec["step_size"]=os.stat().st_size
        print(f"   STEP {rec['step_size']}B")
        try:
            from seekflow_engineering_tools.solidworks.com_client import SolidWorksClient
            swp=dd/f"{cid}.SLDPRT"
            sw=SolidWorksClient(visible=True,part_template=T).connect()
            oks=sw.import_step_as_part(step_path=os,out_sldprt=swp)
            sw.close_all();sw.close()
            if oks and swp.exists(): rec["sldprt"]=str(swp); rec["sldprt_size"]=swp.stat().st_size; print(f"   SLDPRT {rec['sldprt_size']}B")
        except Exception as e: print(f"   SW ERR:{e}")
    else:
        print(f"   FAIL:{err[:200] if err else '?'}")
    results[cid]=rec
    (dd/"summary.json").write_text(json.dumps(rec,indent=2,ensure_ascii=False),encoding="utf-8")

n=sum(1 for r in results.values() if r["ok"])
print(f"\n{'='*70}")
print(f"RESULTS: {n}/{len(results)} OK")
print(f"{'='*70}")
for cid,rec in results.items():
    s="OK" if rec["ok"] else "FAIL"
    print(f"  [{s}] {cid:25s} {rec['name']:18s} {'STEP='+str(rec.get('step_size','?'))+'B':20s} {'SW='+str(rec.get('sldprt_size','?'))+'B' if rec.get('sldprt') else 'no-SW'}")
(OUT/"report_20_parts.json").write_text(json.dumps(results,indent=2,ensure_ascii=False),encoding="utf-8")

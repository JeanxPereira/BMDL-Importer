'''
name: update_check_280.py
author: nBurn
description: Simple script to help prep 2.7x Blender addons for 2.80
version: 0, 0, 0
first released: 2019-09-08
last updated: 2019-09-08


LICENSE (MIT)

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

Except as contained in this notice, the name of the author shall not be used
in advertising or otherwise to promote the sale, use or other dealings in 
this Software without prior written authorization.


 - Usage -
update_check_280.py tests/measureit
python update_check_280.py node_wrangler.py > lines_to_check.txt
'''

TERMS = (
    ("color", "need alpha?"),
    ("viewnumpad", "view_axis"),
    ("get_rna", "get_rna_type"),
    ("viewport_shade", "shading.type"),
    ("TOOLS", "UI"),
    ("LAMP", "light"),
    ("Lamp", "light"),
    ("lamp", "light"),
    (".select", "obj.select_set()"),
    ("backdrop_", "backdrop_offset"),
    ("tessface", "loop_triangles"),
    ("user_preferences", "preferences"),
    (".ops.delete", "context="),
    #("evaluated_get", "foo"),
    ("evaluated_depsgraph_get", "evaluated_get"),
    ("data.meshes.remove", "to_mesh_clear"),
    ("scene.objects.active", "context.active_object", "context.view_layer.objects.active"),
    #("scene.object_bases", "view_layer.objects.active"),
    ("scene.frame_set", "subframe"),
    (".proportional_edit", "use_proportional_edit"),
    ("proportional", "use_proportional_edit"),
    (".prop", "text (keyword)"),
    (".label", "align, text (keywords)"),
    ("row", "align (keyword)"),
    ("show_x_ray", "show_in_front"),
    ("popup_menu", "title (keyword)"),
    (".operator", "text (keyword)"),
    ("object.hide", "object.hide_viewport"),
    (".Group(", ".Collection("),
    (".groups", ".collections"),
    ("dupli_group", "instance_collection"),
    (".link(", "active_layer_collection"),
    ("scene.objects.unlink(", "collection.objects.unlink("),
    (".draw_type", ".display_type"),
    (".draw_size", ".display_size"),
    ("uv_textures.", "uv_layers."),
    (".transform_apply", "scale="),
    ("view_align", "align='WORLD'"),
    ("mesh.primitive", "size, layers"),
    ("transform_orientation", "transform_orientation_slots"),
    ("constraint_orientation", "orient_type"),
    ("show_manipulator", "show_gizmo"),
    ("use_weight_color_range", "view.use_weight_color_rang"),
    ("wm.addon_", "preferences"),
    ("percentage", "factor"),
    ("use_x", "use_axis"),
    ("use_y", "use_axis"),
    ("use_z", "use_axis"),
    ("scene_update_pre", "depsgraph_update_pre"),
    ("scene_update_post", "depsgraph_update_post"),
    ("scene.update", "view_layer.update()"),
    ("use_occlude_geometry", "shading.show_xray"),
    ("event_timer_add", "time_step= (keyword)"),
    ("frame_set", "subframe= (keyword)"),
    ("INFO_MT_", "TOPBAR_MT_"),
    ("_specials", "_context_menu"),
    ("basis", "noise_basis= (keyword)"),
    ("turbulence_vector", "noise_basis= (keyword)"),
    ("tweak_threshold", "drag_threshold"),
    ("cursor_location", "cursor.location"),
    ("snap_element", "snap_elements"),
    (".pivot_point", "transform_pivot_point"),
    ("header_text_set", "_set(None)"),
    ("register_module", "register_class"),
    #("bl_idname", "only needed for Operator"),
    ("Property", ": (annotation)"),
    ("Operator", "_OT"),
    ("Panel", "_PT"),
    ("Menu", "_MT"),
    ("UIList", "_UL"),
    ("keymap_items", "name=name_arg"),
)
#for t in TERMS.split('\n'): print('("' + t + '", ' + '"foo"),')

import os, sys, re


def check_files(files):
    global TERMS
    for file in files:
        split_file = []
        print('\n')
        print("file:", file, '\n')
        with open(file, 'r', errors='ignore') as f:
            split_file = f.read().split('\n')
        if split_file == []:
            continue
        for i, line in enumerate(split_file, 1):
            if line != '':
                for t in TERMS:
                    if t[0] in line:
                        print("%4d" % i, line, '||', t[0], '-', t[1])
                        break


def build_file_set(arg_ls):
    all_files = set()
    for a in arg_ls:
        if os.path.isfile(a):
            if a.endswith('.py'):
                all_files.add(os.path.abspath(a))
        elif os.path.isdir(a) and "__pycache__" not in a:
            dir_walker = os.walk(a, topdown=False)
            for par_dir, sub_dirs, files in dir_walker:
                if "__pycache__" in par_dir:
                    continue
                for f in files:
                    if f.endswith('.py'):
                        full_f = os.path.join(par_dir, f)
                        all_files.add(os.path.abspath(full_f))
    all_files.remove(os.path.abspath(arg_ls[0]))
    return all_files


def main():
    if len(sys.argv) < 2:
        print("Error, not enough arguments.")
        return
    py_files = list(build_file_set(sys.argv))
    if len(py_files) == 0:
        print("Error, no python files found.")
        return
    else:
        py_files.sort()
        check_files(py_files)


main()


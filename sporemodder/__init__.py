import bpy
from bpy_extras.io_utils import ImportHelper, ExportHelper
from . import addon_updater_ops


bl_info = {
    "name": "SporeModder Add-ons",
    "author": "emd4600",
    "blender": (2, 80, 0),
    "version": (2, 6, 0),
    "location": "File > Import-Export",
    "description": "Import Spore and Darkspore .gmdl, .rw4 and .bmdl model formats. Export .rw4 and .anim_t formats.",
    "wiki_url": "https://github.com/emd4600/SporeModder-Blender-Addons#features",
    "tracker_url": "https://github.com/emd4600/SporeModder-Blender-Addons/issues/new",
    "category": "Import-Export"
}


class Preferences(bpy.types.AddonPreferences):

    bl_idname = __package__

    auto_check_update: bpy.props.BoolProperty(
        name="Auto-check for Update",
        description="If enabled, auto-check for updates using an interval",
        default=True,
    )
    updater_intrval_months: bpy.props.IntProperty(
        name='Months',
        description="Number of months between checking for updates",
        default=0,
        min=0
    )
    updater_intrval_days: bpy.props.IntProperty(
        name='Days',
        description="Number of days between checking for updates",
        default=7,
        min=0,
    )
    updater_intrval_hours: bpy.props.IntProperty(
        name='Hours',
        description="Number of hours between checking for updates",
        default=0,
        min=0,
        max=23
    )
    updater_intrval_minutes: bpy.props.IntProperty(
        name='Minutes',
        description="Number of minutes between checking for updates",
        default=0,
        min=0,
        max=59
    )

    def draw(self, context):
        addon_updater_ops.update_settings_ui(self, context)


class ImportGMDL(bpy.types.Operator, ImportHelper):
    bl_idname = "import_my_format.gmdl"
    bl_label = "Import GMDL"
    bl_description = "Import a .gmdl (creation) model from Spore"

    filename_ext = ".gmdl"
    filter_glob: bpy.props.StringProperty(default="*.gmdl", options={'HIDDEN'})

    def execute(self, context):
        from .gmdl_importer import import_gmdl

        with open(self.filepath, 'br') as file:
            return import_gmdl(file, False, self.filepath)

class ImportBMDL(bpy.types.Operator, ImportHelper):
    bl_idname = "import_my_format.bmdl"
    bl_label = "Import BMDL"
    bl_description = "Import a .bmdl (creation) model from Spore"

    filename_ext = ".bmdl"
    filter_glob: bpy.props.StringProperty(default="*.bmdl", options={'HIDDEN'})

    def execute(self, context):
        from .bmdl_importer import import_bmdl

        with open(self.filepath, 'br') as file:
            return import_bmdl(file, False, self.filepath)


class ImportRW4(bpy.types.Operator, ImportHelper):
    bl_idname = "import_my_format.rw4"
    bl_label = "Import RW4"
    bl_description = "Import a .rw4 model from Spore"

    filename_ext = ".rw4"
    filter_glob: bpy.props.StringProperty(default="*.rw4", options={'HIDDEN'})

    import_skeleton: bpy.props.BoolProperty(
        name="Import Skeleton",
        description="",
        default=True
    )
    import_animations: bpy.props.BoolProperty(
        name="Import Animations [EXPERIMENTAL]",
        description="If present, import animation movements and morphs",
        default=True
    )
    import_materials: bpy.props.BoolProperty(
        name="Import Materials",
        description="",
        default=True
    )
    extract_textures: bpy.props.BoolProperty(
        name="Extract Textures",
        default=True
    )
    texture_format: bpy.props.EnumProperty(
        items=(("PNG", "PNG", "Extract the textures as .png images"),
               ("DDS", "DDS", "Extract the textures as the original .dds files; "
                              "Blender might not display them correctly")),
        default="DDS"
    )

    def draw(self, context):
        layout = self.layout

        layout.prop(self, "import_skeleton")
        layout.prop(self, "import_animations")
        layout.prop(self, "import_materials")

        if self.import_materials:
            layout.prop(self, "extract_textures")

            if self.extract_textures:
                layout.prop(self, "texture_format", expand=True)

    def execute(self, context):
        from .rw4_importer import RW4ImporterSettings, import_rw4

        settings = RW4ImporterSettings()
        settings.import_materials = self.import_materials
        settings.import_skeleton = self.import_skeleton
        settings.import_animations = self.import_animations
        settings.extract_textures = self.extract_textures
        settings.texture_format = self.texture_format

        with open(self.filepath, 'br') as file:
            return import_rw4(file, self.filepath, settings)


class ExportRW4(bpy.types.Operator, ExportHelper):
    bl_idname = "export_my_format.rw4"
    bl_label = "Export RW4"
    bl_description = "Export the model to Spore .rw4 format"

    filename_ext = ".rw4"
    filter_glob: bpy.props.StringProperty(default="*.rw4", options={'HIDDEN'})

    def execute(self, context):
        from .rw4_exporter import export_rw4

        with open(self.filepath, 'bw') as file:
            return export_rw4(file)


class ExportAnim(bpy.types.Operator, ExportHelper):
    bl_idname = "export_my_format.anim_t"
    bl_label = "Export Spore Animation"
    bl_description = "Export the skeleton animation to Spore .anim_t format"

    filename_ext = ".anim_t"
    filter_glob: bpy.props.StringProperty(default="*.anim_t", options={'HIDDEN'})

    def execute(self, context):
        from .anim_exporter import export_anim

        with open(self.filepath, 'w') as file:
            return export_anim(file)


def gmdl_importer_menu_func(self, context):
    self.layout.operator(ImportGMDL.bl_idname, text="Spore GMDL Model (.gmdl)")

def bmdl_importer_menu_func(self, context):
    self.layout.operator(ImportBMDL.bl_idname, text="Darkspore BMDL Model (.bmdl)")


def rw4_importer_menu_func(self, context):
    self.layout.operator(ImportRW4.bl_idname, text="Spore RenderWare 4 (.rw4)")


def rw4_exporter_menu_func(self, context):
    self.layout.operator(ExportRW4.bl_idname, text="Spore RenderWare 4 (.rw4)")


def anim_exporter_menu_func(self, context):
    self.layout.operator(ExportAnim.bl_idname, text="Spore Animation (.anim_t)")


classes = (
    Preferences,
    ImportGMDL,
    ImportBMDL,
    ImportRW4,
    ExportRW4,
    ExportAnim
)


def register():
    addon_updater_ops.register(bl_info)

    from . import rw4_material_config, rw4_animation_config, anim_bone_config

    rw4_material_config.register()
    rw4_animation_config.register()
    anim_bone_config.register()

    for c in classes:
        bpy.utils.register_class(c)

    bpy.types.TOPBAR_MT_file_import.append(gmdl_importer_menu_func)
    bpy.types.TOPBAR_MT_file_import.append(bmdl_importer_menu_func)
    bpy.types.TOPBAR_MT_file_import.append(rw4_importer_menu_func)
    bpy.types.TOPBAR_MT_file_export.append(rw4_exporter_menu_func)
    bpy.types.TOPBAR_MT_file_export.append(anim_exporter_menu_func)


def unregister():
    from . import rw4_material_config, rw4_animation_config, anim_bone_config

    rw4_material_config.unregister()
    rw4_animation_config.unregister()
    anim_bone_config.unregister()

    for c in classes:
        bpy.utils.unregister_class(c)

    bpy.types.TOPBAR_MT_file_import.remove(gmdl_importer_menu_func)
    bpy.types.TOPBAR_MT_file_import.remove(bmdl_importer_menu_func)
    bpy.types.TOPBAR_MT_file_import.remove(rw4_importer_menu_func)
    bpy.types.TOPBAR_MT_file_export.remove(rw4_exporter_menu_func)
    bpy.types.TOPBAR_MT_file_export.remove(anim_exporter_menu_func)


if __name__ == "__main__":
    register()

from django import forms

from .models import AnalysisRun, Mall


class VideoUploadForm(forms.ModelForm):
    class Meta:
        model = AnalysisRun
        fields = ["name", "mall", "category", "area", "video"]
        labels = {
            "name": "Nombre del analisis",
            "mall": "Mall",
            "category": "Categoria",
            "area": "Zona o sector",
            "video": "Video",
        }
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Ej: Pasillo norte - viernes 18:00"}),
            "mall": forms.TextInput(attrs={"placeholder": "Ej: Mall Plaza Norte"}),
            "category": forms.TextInput(attrs={"placeholder": "Ej: Retail / Food court / Accesos"}),
            "area": forms.TextInput(attrs={"placeholder": "Ej: Piso 2 - Ala oriente"}),
        }

    def clean_video(self):
        video = self.cleaned_data["video"]
        allowed_extensions = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}
        suffix = "." + video.name.rsplit(".", 1)[-1].lower() if "." in video.name else ""
        if suffix not in allowed_extensions:
            raise forms.ValidationError("Formato de video no soportado.")
        return video


class MallForm(forms.ModelForm):
    class Meta:
        model = Mall
        fields = ["name", "accent_color", "notes"]
        labels = {
            "name": "Nombre del mall",
            "accent_color": "Color de organizacion",
            "notes": "Notas operativas",
        }
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Ej: Mall Plaza Norte"}),
            "accent_color": forms.TextInput(attrs={"type": "color"}),
            "notes": forms.Textarea(attrs={"rows": 4, "placeholder": "Ej: foco en food court, piso 2 y acceso oriente"}),
        }

from django import forms

from .models import AnalysisRun


class VideoUploadForm(forms.ModelForm):
    class Meta:
        model = AnalysisRun
        fields = ["name", "video"]
        labels = {
            "name": "Nombre del estudio",
            "video": "Video",
        }
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Ej: Pasillo norte - viernes 18:00"}),
        }

    def clean_video(self):
        video = self.cleaned_data["video"]
        allowed_extensions = {".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v"}
        suffix = "." + video.name.rsplit(".", 1)[-1].lower() if "." in video.name else ""
        if suffix not in allowed_extensions:
            raise forms.ValidationError("Formato de video no soportado.")
        return video

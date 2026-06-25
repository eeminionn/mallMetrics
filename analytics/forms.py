from django import forms

from .models import AnalysisRun, AppConfiguration, Mall


class VideoUploadForm(forms.ModelForm):
    class Meta:
        model = AnalysisRun
        fields = ["analysis_type", "name", "mall", "category", "area", "video"]
        labels = {
            "analysis_type": "Tipo de analisis",
            "name": "Nombre del analisis",
            "mall": "Establecimiento",
            "category": "Categoria",
            "area": "Zona o sector",
            "video": "Video",
        }
        widgets = {
            "analysis_type": forms.RadioSelect(),
            "name": forms.TextInput(attrs={"placeholder": "Ej: Pasillo norte - viernes 18:00"}),
            "mall": forms.TextInput(attrs={"placeholder": "Ej: Edificio Central"}),
            "category": forms.TextInput(attrs={"placeholder": "Ej: Accesos / Salas / Operacion"}),
            "area": forms.TextInput(attrs={"placeholder": "Ej: Piso 2 - Ala oriente"}),
            "video": forms.FileInput(attrs={"accept": "video/*"}),
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
            "name": "Nombre del establecimiento",
            "accent_color": "Color de organizacion",
            "notes": "Notas operativas",
        }
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Ej: Edificio Central"}),
            "accent_color": forms.TextInput(attrs={"type": "color"}),
            "notes": forms.Textarea(attrs={"rows": 4, "placeholder": "Ej: foco en acceso principal, piso 2 y sector oriente"}),
        }


class AppConfigurationForm(forms.ModelForm):
    openai_api_key = forms.CharField(
        label="API key de OpenAI",
        required=False,
        widget=forms.PasswordInput(attrs={
            "placeholder": "Pega una nueva API key o deja vacio para mantener la actual",
            "autocomplete": "off",
        }),
    )

    class Meta:
        model = AppConfiguration
        fields = ["openai_api_key", "openai_model"]
        labels = {
            "openai_model": "Modelo de analista IA",
        }
        widgets = {
            "openai_model": forms.TextInput(attrs={"placeholder": "Ej: gpt-4o-mini"}),
        }

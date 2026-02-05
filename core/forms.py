from django import forms
from .models import *
from django.contrib.auth.hashers import make_password

class LoginForm(forms.Form):
    correo = forms.EmailField(widget=forms.EmailInput(attrs={
        'class': 'form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-lg text-[#111318] dark:text-white focus:outline-0 focus:ring-2 focus:ring-primary border border-[#dbdfe6] dark:border-gray-700 bg-white dark:bg-slate-800 focus:border-primary h-14 placeholder:text-[#616f89] p-[15px] text-base font-normal leading-normal',
        'placeholder': 'correo@institucion.edu'
    }))
    password = forms.CharField(widget=forms.PasswordInput(attrs={
        'class': 'form-input flex w-full min-w-0 flex-1 resize-none overflow-hidden rounded-lg text-[#111318] dark:text-white focus:outline-0 focus:ring-2 focus:ring-primary border border-[#dbdfe6] dark:border-gray-700 bg-white dark:bg-slate-800 focus:border-primary h-14 placeholder:text-[#616f89] p-[15px] rounded-r-none border-r-0 text-base font-normal leading-normal',
        'placeholder': 'Ingresa tu contraseña',
        'id': 'passwordInput' 
    }))

class DocenteForm(forms.ModelForm):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={
            "class": "form-control",
            "placeholder": "Contraseña"
        })
    )

    class Meta:
        model = Usuario
        fields = ["nombre", "correo", "password"]
        widgets = {
            "nombre": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "Nombre completo"
            }),
            "correo": forms.EmailInput(attrs={
                "class": "form-control",
                "placeholder": "Correo electrónico"
            }),
        }

    def save(self, commit=True):
        usuario = super().save(commit=False)
        usuario.password = make_password(self.cleaned_data["password"])
        if commit:
            usuario.save()
        return usuario
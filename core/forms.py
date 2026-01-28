from django import forms

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
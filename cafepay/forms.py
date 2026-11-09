from django import forms


class ClearTobeCleared(forms.Form):

    def save(self, account, user):
        print(account, user)
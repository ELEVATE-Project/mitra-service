import requests
from django.http import HttpResponse


def generate_pdf_with_gotenberg(html_content):
    gotenberg_url = "http://localhost:3001/forms/chromium/convert/html"

    files = {
        "files": ("index.html", html_content, "text/html"),
    }

    data = {
        "marginTop": "0cm",
        "marginBottom": "0cm",
        "marginLeft": "0cm",
        "marginRight": "0cm",
        "paperWidth": "210mm",
        "paperHeight": "297mm",
    }

    try:
        response = requests.post(gotenberg_url, files=files, data=data)

        if response.status_code == 200:
            pdf = response.content
            http_response = HttpResponse(pdf, content_type="application/pdf")
            http_response["Content-Disposition"] = 'inline; filename="output.pdf"'
            return http_response
        else:
            return HttpResponse(f"Error: {response.status_code} - {response.text}", status=500)
    except Exception as e:
        return HttpResponse(f"An error occurred: {str(e)}", status=500)

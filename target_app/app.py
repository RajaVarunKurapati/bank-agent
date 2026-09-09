from flask import Flask, request, render_template_string, abort

app = Flask(__name__)

# In-memory "core banking" data. No database on purpose — keeps the demo self-contained.
MEMBERS = {
    "12345": {"name": "Jordan Rivera", "savings": "4,210.55", "status": "active"},
    "22222": {"name": "Casey Morgan", "savings": "18,905.00", "status": "active"},
    "33333": {"name": "Restricted Account", "savings": "0.00", "status": "restricted"},
}

PAGE = """
<html><head><title>CoreBank Servicing Console</title></head>
<body bgcolor="#f0f0f0">
<table width="100%" bgcolor="#003366"><tr><td>
  <font color="white" size="5">&nbsp;CoreBank &mdash; Member Servicing</font>
</td></tr></table>
<br>
<table width="600" align="center" bgcolor="white" cellpadding="10"><tr><td>
{{ body|safe }}
</td></tr></table>
</body></html>
"""

@app.route("/")
def home():
    body = """
    <b>Member Lookup</b><br><br>
    <form action="/lookup" method="get">
      Member ID: <input type="text" name="member_id">
      <input type="submit" value="Search">
    </form>
    """
    return render_template_string(PAGE, body=body)

@app.route("/lookup")
def lookup():
    member_id = request.args.get("member_id", "").strip()

    # Exceptional state: record not found -> a BUSINESS OUTCOME, not a crash.
    if member_id not in MEMBERS:
        body = '<font color="red"><b>No such member found.</b></font><br><br>' \
               '<a href="/">Back to lookup</a>'
        return render_template_string(PAGE, body=body)

    member = MEMBERS[member_id]

    # Exceptional state: permission denied for restricted accounts.
    if member["status"] == "restricted":
        body = '<font color="red"><b>Permission denied: account is restricted.</b></font><br><br>' \
               '<a href="/">Back to lookup</a>'
        return render_template_string(PAGE, body=body)

    # Detail view is served inside an iframe on purpose (hostile surface).
    body = f"""
    <b>Member Found</b><br><br>
    <iframe src="/detail?member_id={member_id}" width="100%" height="250"
            frameborder="1"></iframe>
    """
    return render_template_string(PAGE, body=body)

@app.route("/detail")
def detail():
    member_id = request.args.get("member_id", "").strip()
    if member_id not in MEMBERS:
        abort(404)
    m = MEMBERS[member_id]
    body = f"""
    <table border="1" cellpadding="6">
      <tr><td>Name</td><td>{m['name']}</td></tr>
      <tr><td>Member ID</td><td>{member_id}</td></tr>
      <tr><td>Savings Balance</td><td>${m['savings']}</td></tr>
    </table>
    <br>
    <form action="/subaccount" method="get">
      <input type="hidden" name="member_id" value="{member_id}">
      <input type="submit" value="Open Sub-Account">
    </form>
    """
    return render_template_string(PAGE, body=body)

@app.route("/subaccount")
def subaccount():
    member_id = request.args.get("member_id", "").strip()
    if member_id not in MEMBERS:
        abort(404)
    body = f"""
    <b>Confirm New Sub-Account</b><br><br>
    You are opening a new savings sub-account for member {member_id}.<br><br>
    <form action="/confirm" method="get">
      <input type="hidden" name="member_id" value="{member_id}">
      <input type="submit" value="Confirm">
    </form>
    """
    return render_template_string(PAGE, body=body)

@app.route("/confirm")
def confirm():
    member_id = request.args.get("member_id", "").strip()
    body = f'<font color="green"><b>Success:</b></font> ' \
           f'Sub-account opened for member {member_id}.<br>' \
           f'Reference: SUB-{member_id}-001'
    return render_template_string(PAGE, body=body)

if __name__ == "__main__":
    app.run(port=5000, debug=True)
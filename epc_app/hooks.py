app_name = "epc_app"
app_title = "epc_app"
app_publisher = "yahya basalama"
app_description = "app for AHRAM requirments"
app_email = "syahya8@gmail.com"
app_license = "mit"





doc_events = {
    "Sales Invoice": {
        "validate": [
            "epc_app.validations.freeze_datetime.validate_freeze_datetime",
            "epc_app.validations.stock_rules.enforce_update_stock_and_warehouse",
        ]
    },
    "Purchase Invoice": {
        "validate": [
            "epc_app.validations.freeze_datetime.validate_freeze_datetime",
            "epc_app.validations.stock_rules.enforce_update_stock_and_warehouse",
        ],
        "before_submit": "epc_app.validations.cash_balance.validate_cash_balance_before_submit",
    },
    "Payment Entry": {
        "validate": "epc_app.validations.freeze_datetime.validate_freeze_datetime",
        "before_submit": "epc_app.validations.cash_balance.validate_cash_balance_before_submit",
    },
    "Journal Entry": {"validate": "epc_app.validations.freeze_datetime.validate_freeze_datetime"},
    "Sales Order": {"validate": "epc_app.validations.freeze_datetime.validate_freeze_datetime"},
    "Quotation": {"validate": "epc_app.validations.freeze_datetime.validate_freeze_datetime"},
}
doctype_js = {
    "Landed Cost Voucher": "public/js/landed_cost_voucher.js",
}

# Apps
# ------------------

# required_apps = []

# Each item in the list will be shown as an app in the apps page
# add_to_apps_screen = [
# 	{
# 		"name": "epc_app",
# 		"logo": "/assets/epc_app/logo.png",
# 		"title": "epc_app",
# 		"route": "/epc_app",
# 		"has_permission": "epc_app.api.permission.has_app_permission"
# 	}
# ]

# Includes in <head>
# ------------------

# include js, css files in header of desk.html
# app_include_css = "/assets/epc_app/css/epc_app.css"
# app_include_js = "/assets/epc_app/js/epc_app.js"

# include js, css files in header of web template
# web_include_css = "/assets/epc_app/css/epc_app.css"
# web_include_js = "/assets/epc_app/js/epc_app.js"

# include custom scss in every website theme (without file extension ".scss")
# website_theme_scss = "epc_app/public/scss/website"

# include js, css files in header of web form
# webform_include_js = {"doctype": "public/js/doctype.js"}
# webform_include_css = {"doctype": "public/css/doctype.css"}

# include js in page
# page_js = {"page" : "public/js/file.js"}

# include js in doctype views
# doctype_js = {"doctype" : "public/js/doctype.js"}
# doctype_list_js = {"doctype" : "public/js/doctype_list.js"}
# doctype_tree_js = {"doctype" : "public/js/doctype_tree.js"}
# doctype_calendar_js = {"doctype" : "public/js/doctype_calendar.js"}

# Svg Icons
# ------------------
# include app icons in desk
# app_include_icons = "epc_app/public/icons.svg"

# Home Pages
# ----------

# application home page (will override Website Settings)
# home_page = "login"

# website user home page (by Role)
# role_home_page = {
# 	"Role": "home_page"
# }

# Generators
# ----------

# automatically create page for each record of this doctype
# website_generators = ["Web Page"]

# automatically load and sync documents of this doctype from downstream apps
# importable_doctypes = [doctype_1]

# Jinja
# ----------

# add methods and filters to jinja environment
# jinja = {
# 	"methods": "epc_app.utils.jinja_methods",
# 	"filters": "epc_app.utils.jinja_filters"
# }

# Installation
# ------------

# before_install = "epc_app.install.before_install"
# after_install = "epc_app.install.after_install"

# Uninstallation
# ------------

# before_uninstall = "epc_app.uninstall.before_uninstall"
# after_uninstall = "epc_app.uninstall.after_uninstall"

# Integration Setup
# ------------------
# To set up dependencies/integrations with other apps
# Name of the app being installed is passed as an argument

# before_app_install = "epc_app.utils.before_app_install"
# after_app_install = "epc_app.utils.after_app_install"

# Integration Cleanup
# -------------------
# To clean up dependencies/integrations with other apps
# Name of the app being uninstalled is passed as an argument

# before_app_uninstall = "epc_app.utils.before_app_uninstall"
# after_app_uninstall = "epc_app.utils.after_app_uninstall"

# Desk Notifications
# ------------------
# See frappe.core.notifications.get_notification_config

# notification_config = "epc_app.notifications.get_notification_config"

# Permissions
# -----------
# Permissions evaluated in scripted ways

# permission_query_conditions = {
# 	"Event": "frappe.desk.doctype.event.event.get_permission_query_conditions",
# }
#
# has_permission = {
# 	"Event": "frappe.desk.doctype.event.event.has_permission",
# }

# Document Events
# ---------------
# Hook on document methods and events

# doc_events = {
# 	"*": {
# 		"on_update": "method",
# 		"on_cancel": "method",
# 		"on_trash": "method"
# 	}
# }

# Scheduled Tasks
# ---------------

# scheduler_events = {
# 	"all": [
# 		"epc_app.tasks.all"
# 	],
# 	"daily": [
# 		"epc_app.tasks.daily"
# 	],
# 	"hourly": [
# 		"epc_app.tasks.hourly"
# 	],
# 	"weekly": [
# 		"epc_app.tasks.weekly"
# 	],
# 	"monthly": [
# 		"epc_app.tasks.monthly"
# 	],
# }

# Testing
# -------

# before_tests = "epc_app.install.before_tests"

# Extend DocType Class
# ------------------------------
#
# Specify custom mixins to extend the standard doctype controller.
# extend_doctype_class = {
# 	"Task": "epc_app.custom.task.CustomTaskMixin"
# }

# Overriding Methods
# ------------------------------
#
# override_whitelisted_methods = {
# 	"frappe.desk.doctype.event.event.get_events": "epc_app.event.get_events"
# }
#
# each overriding function accepts a `data` argument;
# generated from the base implementation of the doctype dashboard,
# along with any modifications made in other Frappe apps
# override_doctype_dashboards = {
# 	"Task": "epc_app.task.get_dashboard_data"
# }

# exempt linked doctypes from being automatically cancelled
#
# auto_cancel_exempted_doctypes = ["Auto Repeat"]

# Ignore links to specified DocTypes when deleting documents
# -----------------------------------------------------------

# ignore_links_on_delete = ["Communication", "ToDo"]

# Request Events
# ----------------
# before_request = ["epc_app.utils.before_request"]
# after_request = ["epc_app.utils.after_request"]

# Job Events
# ----------
# before_job = ["epc_app.utils.before_job"]
# after_job = ["epc_app.utils.after_job"]

# User Data Protection
# --------------------

# user_data_fields = [
# 	{
# 		"doctype": "{doctype_1}",
# 		"filter_by": "{filter_by}",
# 		"redact_fields": ["{field_1}", "{field_2}"],
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_2}",
# 		"filter_by": "{filter_by}",
# 		"partial": 1,
# 	},
# 	{
# 		"doctype": "{doctype_3}",
# 		"strict": False,
# 	},
# 	{
# 		"doctype": "{doctype_4}"
# 	}
# ]

# Authentication and authorization
# --------------------------------

# auth_hooks = [
# 	"epc_app.auth.validate"
# ]

# Automatically update python controller files with type annotations for this app.
# export_python_type_annotations = True

# default_log_clearing_doctypes = {
# 	"Logging DocType Name": 30  # days to retain logs
# }

# Translation
# ------------
# List of apps whose translatable strings should be excluded from this app's translations.
# ignore_translatable_strings_from = []


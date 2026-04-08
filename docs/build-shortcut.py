"""Build the Dead-Drop iOS Shortcut as a signed .shortcut file."""
import plistlib
import subprocess
import sys
import os

SERVER = "https://YOUR-SERVER-HERE.example.com"

# Group UUIDs for control flow blocks
GID_IF_URL = "B0000001-0000-0000-0000-000000000001"
GID_REPEAT = "B0000001-0000-0000-0000-000000000002"
GID_IF_COMPLETED = "B0000001-0000-0000-0000-000000000003"
GID_IF_FAILED = "B0000001-0000-0000-0000-000000000004"
GID_IF_DONE1 = "B0000001-0000-0000-0000-000000000005"
GID_IF_DONE2 = "B0000001-0000-0000-0000-000000000006"
GID_IF_DONE0 = "B0000001-0000-0000-0000-000000000007"
GID_FOR_EACH = "B0000001-0000-0000-0000-000000000008"
GID_IF_UPLOAD_OK = "B0000001-0000-0000-0000-00000000000A"


def var_ref(name):
    """Variable reference for use as action parameter values (WFInput, etc.)."""
    return {
        "Value": {"VariableName": name, "Type": "Variable"},
        "WFSerializationType": "WFTextTokenAttachment",
    }


def var_token(name):
    """Variable reference for embedding inside WFTextTokenString attachmentsByRange."""
    return {"VariableName": name, "Type": "Variable"}


def shortcut_input():
    """Reference the Shortcut Input (Share Sheet)."""
    return {
        "Value": {"Type": "ExtensionInput"},
        "WFSerializationType": "WFTextTokenAttachment",
    }


def text_with_vars(parts):
    """Build a WFTextTokenString from a list of (string, var_name_or_None) tuples.

    Uses var_token (raw dict) not var_ref (wrapped) for text embeddings.
    """
    full_string = ""
    attachments = {}
    for text_part, var_name in parts:
        if var_name:
            pos = len(full_string) + len(text_part)
            full_string += text_part + "\ufffc"
            attachments[f"{{{pos}, 1}}"] = var_token(var_name)
        else:
            full_string += text_part
    return {
        "Value": {"attachmentsByRange": attachments, "string": full_string},
        "WFSerializationType": "WFTextTokenString",
    }


def cond_string(s):
    """Wrap a condition comparison string as WFTextTokenString."""
    return {
        "WFSerializationType": "WFTextTokenString",
        "Value": {"string": s, "attachmentsByRange": {}},
    }


def var_as_input(name):
    """Variable reference formatted as WFInput for If conditions (WFTextTokenString with embedded var)."""
    return {
        "WFSerializationType": "WFTextTokenString",
        "Value": {
            "string": "\ufffc",
            "attachmentsByRange": {
                "{0, 1}": var_token(name),
            },
        },
    }


def act(identifier, params=None):
    """Build a shortcut action dict."""
    return {
        "WFWorkflowActionIdentifier": identifier,
        "WFWorkflowActionParameters": params or {},
    }


actions = []

# ============================================================
# SETUP: Get URLs from Share Sheet input
# ============================================================

# Get URLs directly from Shortcut Input (must use shortcut_input() directly, not via variable)
actions.append(act("is.workflow.actions.detect.link", {"WFInput": shortcut_input()}))
actions.append(act("is.workflow.actions.setvariable", {"WFVariableName": "urls"}))

# Get First Item from URLs
actions.append(act("is.workflow.actions.getitemfromlist", {
    "WFInput": var_ref("urls"),
    "WFItemSpecifier": "First Item",
}))
actions.append(act("is.workflow.actions.setvariable", {"WFVariableName": "firstUrl"}))

# ============================================================
# IF URLs has any value -> URL branch
# ============================================================
actions.append(act("is.workflow.actions.conditional", {
    "GroupingIdentifier": GID_IF_URL,
    "WFControlFlowMode": 0,
    "WFCondition": 100,  # has any value
    "WFInput": {"Type": "Variable", "Variable": var_ref("urls")},
}))

# POST to /api/upload/url with JSON body {"url": firstUrl}
actions.append(act("is.workflow.actions.downloadurl", {
    "WFURL": f"{SERVER}/api/upload/url",
    "WFHTTPMethod": "POST",
    "WFHTTPBodyType": "JSON",
    "WFJSONValues": {"Value": {"WFDictionaryFieldValueItems": [
        {"WFItemType": 0,
         "WFKey": {"Value": {"string": "url"}, "WFSerializationType": "WFTextTokenString"},
         "WFValue": text_with_vars([("", "firstUrl")]),
        },
    ]}, "WFSerializationType": "WFDictionaryFieldValue"},
}))
actions.append(act("is.workflow.actions.setvariable", {"WFVariableName": "submitResponse"}))

# Get dictionary, extract job_id
actions.append(act("is.workflow.actions.detect.dictionary", {"WFInput": var_ref("submitResponse")}))
actions.append(act("is.workflow.actions.setvariable", {"WFVariableName": "submitDict"}))

actions.append(act("is.workflow.actions.getvalueforkey", {
    "WFInput": var_ref("submitDict"),
    "WFDictionaryKey": "job_id",
}))
actions.append(act("is.workflow.actions.setvariable", {"WFVariableName": "jobid"}))

# No initial done variable needed -- we check for field presence

# ============================================================
# REPEAT 100 times (polling loop)
# ============================================================
actions.append(act("is.workflow.actions.repeat.count", {
    "GroupingIdentifier": GID_REPEAT,
    "WFControlFlowMode": 0,
    "WFRepeatCount": 30,
}))

# Only poll if isDone does NOT have any value (skip after first completion/failure)
GID_IF_NOT_DONE = "B0000001-0000-0000-0000-00000000000B"
actions.append(act("is.workflow.actions.conditional", {
    "GroupingIdentifier": GID_IF_NOT_DONE,
    "WFControlFlowMode": 0,
    "WFCondition": 101,  # does NOT have any value
    "WFInput": {"Type": "Variable", "Variable": var_ref("isDone")},
}))

# Build poll URL and GET it
actions.append(act("is.workflow.actions.gettext", {
    "WFTextActionText": text_with_vars([
        (f"{SERVER}/api/upload/url/status/", None),
        ("", "jobid"),
    ]),
}))
actions.append(act("is.workflow.actions.downloadurl", {
    "WFHTTPMethod": "GET",
}))
actions.append(act("is.workflow.actions.setvariable", {"WFVariableName": "pollRaw"}))

# Parse JSON into dictionary
actions.append(act("is.workflow.actions.detect.dictionary", {
    "WFInput": var_ref("pollRaw"),
}))
actions.append(act("is.workflow.actions.setvariable", {"WFVariableName": "pollDict"}))

# Check "result" key
actions.append(act("is.workflow.actions.getvalueforkey", {
    "WFInput": var_ref("pollDict"),
    "WFDictionaryKey": "result",
}))
actions.append(act("is.workflow.actions.setvariable", {"WFVariableName": "checkResult"}))

# If result has any value -> set isDone and alert
actions.append(act("is.workflow.actions.conditional", {
    "GroupingIdentifier": GID_IF_COMPLETED,
    "WFControlFlowMode": 0,
    "WFCondition": 100,
    "WFInput": {"Type": "Variable", "Variable": var_ref("checkResult")},
}))
actions.append(act("is.workflow.actions.gettext", {
    "WFTextActionText": {"Value": {"string": "yes", "attachmentsByRange": {}}, "WFSerializationType": "WFTextTokenString"},
}))
actions.append(act("is.workflow.actions.setvariable", {"WFVariableName": "isDone"}))
actions.append(act("is.workflow.actions.alert", {
    "WFAlertActionTitle": "Dead-Drop",
    "WFAlertActionMessage": "Upload complete",
}))
actions.append(act("is.workflow.actions.exit", {}))
actions.append(act("is.workflow.actions.conditional", {
    "GroupingIdentifier": GID_IF_COMPLETED,
    "WFControlFlowMode": 2,
}))

# Check "error" key
actions.append(act("is.workflow.actions.getvalueforkey", {
    "WFInput": var_ref("pollDict"),
    "WFDictionaryKey": "error",
}))
actions.append(act("is.workflow.actions.setvariable", {"WFVariableName": "checkError"}))

# If error has any value -> set isDone and alert
actions.append(act("is.workflow.actions.conditional", {
    "GroupingIdentifier": GID_IF_FAILED,
    "WFControlFlowMode": 0,
    "WFCondition": 100,
    "WFInput": {"Type": "Variable", "Variable": var_ref("checkError")},
}))
actions.append(act("is.workflow.actions.gettext", {
    "WFTextActionText": {"Value": {"string": "yes", "attachmentsByRange": {}}, "WFSerializationType": "WFTextTokenString"},
}))
actions.append(act("is.workflow.actions.setvariable", {"WFVariableName": "isDone"}))
actions.append(act("is.workflow.actions.alert", {
    "WFAlertActionTitle": "Dead-Drop",
    "WFAlertActionMessage": "Upload failed",
}))
actions.append(act("is.workflow.actions.exit", {}))
actions.append(act("is.workflow.actions.conditional", {
    "GroupingIdentifier": GID_IF_FAILED,
    "WFControlFlowMode": 2,
}))

# End If isDone does not have any value
actions.append(act("is.workflow.actions.conditional", {
    "GroupingIdentifier": GID_IF_NOT_DONE,
    "WFControlFlowMode": 2,
}))

# End Repeat
actions.append(act("is.workflow.actions.repeat.count", {
    "GroupingIdentifier": GID_REPEAT,
    "WFControlFlowMode": 2,
}))
# End If (URL branch -- no Otherwise, URL only)
actions.append(act("is.workflow.actions.conditional", {
    "GroupingIdentifier": GID_IF_URL,
    "WFControlFlowMode": 2,
}))

# ============================================================
# Build plist and sign
# ============================================================
shortcut = {
    "WFWorkflowMinimumClientVersion": 900,
    "WFWorkflowMinimumClientVersionString": "900",
    "WFWorkflowHasShortcutInputVariables": True,
    "WFWorkflowNoInputBehavior": {
        "Name": "WFWorkflowNoInputBehaviorGetClipboard",
        "Parameters": {},
    },
    "WFWorkflowIcon": {
        "WFWorkflowIconStartColor": 463140863,
        "WFWorkflowIconGlyphNumber": 59511,
    },
    "WFWorkflowTypes": ["ActionExtension"],
    "WFWorkflowInputContentItemClasses": [
        "WFAppStoreAppContentItem",
        "WFArticleContentItem",
        "WFContactContentItem",
        "WFDateContentItem",
        "WFEmailAddressContentItem",
        "WFGenericFileContentItem",
        "WFImageContentItem",
        "WFiTunesProductContentItem",
        "WFLocationContentItem",
        "WFDCMapsLinkContentItem",
        "WFAVAssetContentItem",
        "WFPDFContentItem",
        "WFPhoneNumberContentItem",
        "WFRichTextContentItem",
        "WFSafariWebPageContentItem",
        "WFStringContentItem",
        "WFURLContentItem",
    ],
    "WFWorkflowActions": actions,
}

unsigned = "/tmp/dead-drop-unsigned.shortcut"
signed = os.path.expanduser("~/Downloads/Dead-Drop.shortcut")

with open(unsigned, "wb") as f:
    plistlib.dump(shortcut, f, fmt=plistlib.FMT_BINARY)

result = subprocess.run(
    ["shortcuts", "sign", "--mode", "anyone", "--input", unsigned, "--output", signed],
    capture_output=True, text=True,
)
if result.returncode == 0:
    print(f"Built: {signed}")
else:
    print(f"Failed: {result.stderr}")
    sys.exit(1)

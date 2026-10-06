# ---------------------------------------------------------------------------
# Registry — Container Registry Personal Edition.
#
# Three things about Personal Edition stay in the console, because neither the
# API nor the provider reaches them:
#
#   - The instance itself (crpi-...). It is created by hand, once per account;
#     these resources land in whichever instance the account has in `region`.
#   - The registry login password. The provider refuses to work without one.
#   - The GitHub source and the build rules: `main` builds `latest`, and one
#     rule per release tag `vX.Y.Z` builds `X.Y.Z` from the root Dockerfile.
#
# Both resources are deprecated in favour of their alicloud_cr_ee_* versions,
# which only reach Enterprise Edition instances; the plan warns about it. For
# Personal Edition they are the only resources there are.
# ---------------------------------------------------------------------------

resource "alicloud_cr_namespace" "main" {
  name               = var.namespace
  auto_create        = true
  default_visibility = "PRIVATE"
}

resource "alicloud_cr_repo" "main" {
  namespace = alicloud_cr_namespace.main.name
  name      = "resumix"
  summary   = "resumix_images"
  repo_type = "PRIVATE"
}


# ---------------------------------------------------------------------------
# Function — Function Compute 3.0, custom container.
# ---------------------------------------------------------------------------

data "alicloud_account" "current" {}

locals {
  # The VPC endpoint: the pull never leaves Alibaba's network.
  image = "${alicloud_cr_repo.main.domain_list["vpc"]}/${alicloud_cr_repo.main.namespace}/${alicloud_cr_repo.main.name}:${var.image_tag}"

  # Merging the sensitive map as a whole would hide every variable in a plan.
  # Marking each secret on its own keeps a model override visible as it changes.
  environment = merge(var.environment, {
    for name, value in nonsensitive(var.secrets) : name => sensitive(value)
  })
}

resource "alicloud_fcv3_function" "main" {
  function_name = var.function_name
  description   = "resumix function"
  runtime       = "custom-container"
  # Required by the API, never called by a custom container.
  handler = "index.handler"
  role    = "acs:ram::${data.alicloud_account.current.id}:role/aliyunfcdefaultrole"

  cpu                  = 0.35
  memory_size          = 512
  disk_size            = 512
  timeout              = 1200
  idle_timeout         = 900
  instance_concurrency = 200
  # The model providers are on the public internet.
  internet_access = true

  # A CV job lives in the work directory of the instance that started it. The
  # client keeps one HTTP session per run, so this cookie brings its polls back
  # to that instance instead of one that would answer 404.
  session_affinity = "GENERATED_COOKIE"
  # Compared as a plain string with what the API returns: every key stays,
  # including the null.
  session_affinity_config = jsonencode({
    disableSessionIdReuse         = false
    enableAutoPause               = false
    enableAutoResume              = null
    sessionConcurrencyPerInstance = 1
    sessionIdleTimeoutInSeconds   = 600
    sessionTTLInSeconds           = 600
  })

  environment_variables = local.environment

  # The console writes this block; leaving it out would show as a change.
  invocation_restriction {
    disable = false
  }

  custom_container_config {
    image = local.image
    port  = 8080

    # The one route the server answers without a token.
    health_check_config {
      http_get_url      = "/healthz"
      period_seconds    = 3
      timeout_seconds   = 1
      failure_threshold = 3
      success_threshold = 1
    }
  }

  log_config {
    project                 = var.log_project
    logstore                = var.log_logstore
    enable_request_metrics  = true
    enable_instance_metrics = true
    log_begin_rule          = "DefaultRegex"
  }
}

# The trigger is bound to the alias rather than the function, so the alias can
# move to a published version without the URL changing.
resource "alicloud_fcv3_alias" "main" {
  function_name = alicloud_fcv3_function.main.function_name
  alias_name    = "resumix"
  version_id    = "LATEST"
  description   = "latest version of resumix"
}

resource "alicloud_fcv3_trigger" "main" {
  function_name = alicloud_fcv3_function.main.function_name
  trigger_name  = "default"
  trigger_type  = "http"
  qualifier     = alicloud_fcv3_alias.main.alias_name

  # Bearer auth at the trigger: a request without the token is turned away
  # before it reaches an instance.
  trigger_config = jsonencode({
    authType           = "bearer"
    disableURLInternet = false
    methods            = ["GET", "POST", "PUT", "DELETE"]
    authConfig = {
      bearerFormat = "opaque"
      opaqueTokenConfig = {
        tokens = [{
          enable    = true
          tokenName = "resumix-client"
          tokenData = var.api_token
        }]
      }
    }
  })

  lifecycle {
    # FC stamps every token with an id and timestamps, and the provider
    # compares this JSON verbatim, so what is written never matches what is
    # read back. It is sent once, at creation; rotate the token in the console.
    ignore_changes = [trigger_config]
  }
}

# Reserved concurrency counts every instance of the function, so this is also
# its ceiling: a cap on spend.
resource "alicloud_fcv3_concurrency_config" "main" {
  function_name        = alicloud_fcv3_function.main.function_name
  reserved_concurrency = 2
}

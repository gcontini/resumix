# Adopts the resources that were created by hand in the console, so the first
# apply takes them over instead of failing on "already exists". Once they are
# in the state these blocks do nothing. Delete this file to deploy from
# scratch into an account that has none of them.

import {
  to = alicloud_cr_namespace.main
  id = var.namespace
}

import {
  to = alicloud_cr_repo.main
  id = "${var.namespace}/resumix"
}

import {
  to = alicloud_fcv3_function.main
  id = var.function_name
}

import {
  to = alicloud_fcv3_alias.main
  id = "${var.function_name}:resumix"
}

import {
  to = alicloud_fcv3_trigger.main
  id = "${var.function_name}:default"
}

import {
  to = alicloud_fcv3_concurrency_config.main
  id = var.function_name
}

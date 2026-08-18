<script setup lang="ts">
import { computed, ref } from 'vue'

import { Button, Dialog, ErrorMessage, FormControl } from 'frappe-ui'

import { sitesApi } from '@/api/sites'
import { apiErrorMessage } from '@/api/client'
import { fmtDateTime } from '@/utils/taskFormat'

const props = defineProps<{ siteName: string; backup: object | null }>()

const visible = ref(false)
const targetName = ref('')
const adminPassword = ref('')
const includePublic = ref(true)
const includePrivate = ref(true)
const submitting = ref(false)
const error = ref('')

const open = () => {
  visible.value = true
  targetName.value = ''
  adminPassword.value = ''
  error.value = ''
}

defineExpose({ open })

const files = computed(() => (props.backup?.files ?? []) as Array<{ kind: string; path: string | null }>)
const fileFor = (kind: string) => files.value.find((f) => f.kind === kind) ?? null
const hasPublic = computed(() => !!fileFor('public-file'))
const hasPrivate = computed(() => !!fileFor('private-file'))
const fileNote = (kind: string) => {
  const file = fileFor(kind)
  if (!file) return ''
  return file.path ? 'on this server' : 'in R2 - will be fetched first'
}

const close = () => {
  if (!submitting.value) visible.value = false
}

const submit = async () => {
  if (!targetName.value.trim()) {
    error.value = 'A site name is required.'
    return
  }
  if (!adminPassword.value) {
    error.value = 'An administrator password is required.'
    return
  }
  submitting.value = true
  error.value = ''
  if (!props.backup) return
  try {
    const result = await sitesApi.backups.restore(props.siteName, props.backup.timestamp, {
      target_name: targetName.value.trim(),
      admin_password: adminPassword.value,
      include_public_files: includePublic.value,
      include_private_files: includePrivate.value,
    })
    if (result.error) {
      error.value = apiErrorMessage(result, 'Restore failed.')
      return
    }
    visible.value = false
  } catch (e) {
    error.value = e.message || 'Restore failed.'
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <Dialog v-model="visible" title="Restore backup" size="md" @close="close">
    <div class="space-y-4">
      <div class="rounded-7 border border-outline-gray-2 p-3">
        <p class="text-ink-gray-8 text-sm font-medium">
          {{ backup ? fmtDateTime(backup.created_at) : '' }}
        </p>
        <p class="mt-1 text-ink-gray-5 text-p-sm leading-relaxed">
          Database is always restored.
          <span v-if="hasPublic">Public files are {{ fileNote('public-file') }}.</span>
          <span v-if="hasPrivate">Private files are {{ fileNote('private-file') }}.</span>
        </p>
      </div>

      <FormControl label="New site name" required v-model="targetName">
      </FormControl>

      <FormControl
        label="Administrator password"
        type="password"
        required
        v-model="adminPassword"
        help="Used to provision the site. The restored site keeps the Administrator password saved in the backup."
      >
      </FormControl>

      <div class="flex flex-col gap-2">
        <label v-if="hasPublic" class="flex items-center gap-2 text-ink-gray-7 text-sm">
          <input v-model="includePublic" type="checkbox" class="size-4" />
          Include public files
        </label>
        <label v-if="hasPrivate" class="flex items-center gap-2 text-ink-gray-7 text-sm">
          <input v-model="includePrivate" type="checkbox" class="size-4" />
          Include private files
        </label>
      </div>

      <div class="rounded-7 bg-amber-50 p-3 text-amber-700 text-p-sm leading-relaxed">
        Restores into a <strong>new site</strong>. {{ siteName }} and its backups are not
        touched.
      </div>

      <ErrorMessage v-if="error" :message="error" class="mt-2" />

      <div class="flex justify-end gap-2 mt-4">
        <Button variant="ghost" :disabled="submitting" @click="close">Cancel</Button>
        <Button :loading="submitting" @click="submit">Restore</Button>
      </div>
    </div>
  </Dialog>
</template>
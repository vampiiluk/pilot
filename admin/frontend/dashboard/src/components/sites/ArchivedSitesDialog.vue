<script setup lang="ts">
import { ref } from 'vue'

import { Button, Dialog, Dropdown, ErrorMessage, FormControl, toast } from 'frappe-ui'

import { sitesApi } from '@/api/sites'
import { apiErrorMessage } from '@/api/client'
import { fmtDateTime } from '@/utils/taskFormat'
import { openTaskDetailPage } from '@/utils/taskRoute'
import { useRouter } from 'vue-router'

const router = useRouter()

const visible = ref(false)
const loading = ref(false)
const error = ref('')
const archived = ref([])
const liveSites = ref([])
const expanded = ref<string | null>(null)
const runsBySite = ref<Record<string, Array<object>>>({})

const fmtBytes = (b) =>
  !b ? '-' : b < 1024 ** 2 ? `${(b / 1024).toFixed(1)} KB` : `${(b / 1024 ** 2).toFixed(1)} MB`

const open = async () => {
  visible.value = true
  await refreshAll()
}

const refreshAll = async () => {
  loading.value = true
  error.value = ''
  try {
    const [sites, live] = await Promise.all([sitesApi.backups.archived.list(), sitesApi.list()])
    archived.value = sites ?? []
    liveSites.value = (live ?? []).map((s) => s.name)
    if (expanded.value) await loadRuns(expanded.value)
  } catch (e) {
    error.value = e.message || 'Could not load archived sites.'
  } finally {
    loading.value = false
  }
}

const loadRuns = async (name: string) => {
  try {
    runsBySite.value[name] = await sitesApi.backups.archived.backups(name)
  } catch {
    runsBySite.value[name] = []
  }
}

const toggle = (name: string) => {
  if (expanded.value === name) {
    expanded.value = null
    return
  }
  expanded.value = name
  if (!runsBySite.value[name]) loadRuns(name)
}

const fileOf = (set, kind) => set.files?.find((f) => f.kind === kind) ?? null

const moveTarget = ref<Record<string, string>>({})
const moving = ref(false)

const moveRun = async (archivedName: string, run: object) => {
  const target = moveTarget.value[archivedName]
  if (!target) {
    toast.error('Choose a site to move the backup into first.')
    return
  }
  moving.value = true
  error.value = ''
  try {
    const result = await sitesApi.backups.archived.move(archivedName, run.timestamp, target)
    if (result.task_id) openTaskDetailPage(router, result.task_id)
    else error.value = apiErrorMessage(result, 'Move failed.')
    await loadRuns(archivedName)
  } catch (e) {
    error.value = e.message || 'Move failed.'
  } finally {
    moving.value = false
  }
}

const deleteRun = async (archivedName: string, run: object) => {
  error.value = ''
  try {
    const result = await sitesApi.backups.archived.deleteRun(archivedName, run.timestamp)
    if (result.task_id) openTaskDetailPage(router, result.task_id)
    else error.value = apiErrorMessage(result, 'Delete failed.')
    await loadRuns(archivedName)
    await refreshAll()
  } catch (e) {
    error.value = e.message || 'Delete failed.'
  }
}

const deleteSite = async (name: string) => {
  error.value = ''
  try {
    const result = await sitesApi.backups.archived.deleteSite(name)
    if (result.task_id) openTaskDetailPage(router, result.task_id)
    else error.value = apiErrorMessage(result, 'Delete failed.')
    await refreshAll()
  } catch (e) {
    error.value = e.message || 'Delete failed.'
  }
}

defineExpose({ open })
</script>

<template>
  <Dialog v-model="visible" title="Archived sites" size="lg">
    <ErrorMessage v-if="error" :message="error" class="mb-3" />
    <div v-if="loading && !archived.length" class="py-10 text-center text-ink-gray-5 text-sm">
      Loading archived sites…
    </div>
    <div v-else-if="!archived.length" class="py-10 text-center text-ink-gray-5 text-sm">
      No archived sites. Dropped sites keep a copy here until you delete it.
    </div>
    <div v-else class="space-y-3">
      <div
        v-for="site in archived"
        :key="site.name"
        class="border border-outline-gray-2 rounded-6 bg-surface-base"
      >
        <button
          class="w-full flex items-center justify-between gap-3 px-3 py-2.5 text-left"
          @click="toggle(site.name)"
        >
          <div class="min-w-0">
            <p class="text-ink-gray-8 text-sm font-medium truncate">{{ site.name }}</p>
            <p class="text-ink-gray-5 text-p-sm">
              {{ site.backup_count }} backup{{ site.backup_count === 1 ? '' : 's' }} ·
              {{ fmtBytes(site.size_bytes) }} ·
              {{ fmtDateTime(new Date(site.created_at * 1000).toISOString()) }}
            </p>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <Dropdown
              :options="[
                {
                  label: 'Delete archive',
                  icon: 'lucide-trash-2',
                  theme: 'red',
                  onClick: () => deleteSite(site.name),
                },
              ]"
            >
              <template #default="{ open: dropdownOpen }">
                <Button
                  variant="ghost"
                  size="sm"
                  :active="dropdownOpen"
                  icon="lucide-ellipsis"
                  label="Archive actions"
                  tooltip="Actions"
                />
              </template>
            </Dropdown>
            <span
              class="size-4 text-ink-gray-5"
              :class="expanded === site.name ? 'lucide-chevron-up' : 'lucide-chevron-down'"
            />
          </div>
        </button>

        <div v-if="expanded === site.name" class="border-t border-outline-gray-1 px-3 py-3 space-y-2">
          <div
            v-for="run in runsBySite[site.name] || []"
            :key="run.timestamp"
            class="flex flex-wrap items-center gap-3 rounded-6 border border-outline-gray-1 px-3 py-2"
          >
            <p class="text-ink-gray-7 text-sm font-medium w-40">{{ fmtDateTime(run.created_at) }}</p>
            <p class="text-ink-gray-5 text-p-sm">DB {{ fmtBytes(fileOf(run, 'database')?.size_bytes) }}</p>
            <p class="text-ink-gray-5 text-p-sm">Pub {{ fmtBytes(fileOf(run, 'public-file')?.size_bytes) }}</p>
            <p class="text-ink-gray-5 text-p-sm">Priv {{ fmtBytes(fileOf(run, 'private-file')?.size_bytes) }}</p>
            <div class="flex-1" />
            <FormControl
              class="w-48"
              :options="liveSites.filter((s) => s !== site.name)"
              placeholder="Move into…"
              size="sm"
              v-model="moveTarget[site.name]"
            />
            <Button size="sm" variant="subtle" :disabled="moving" @click="moveRun(site.name, run)">
              Move
            </Button>
            <Button size="sm" variant="ghost" theme="red" @click="deleteRun(site.name, run)">
              Delete
            </Button>
          </div>
          <p v-if="!(runsBySite[site.name] || []).length" class="text-ink-gray-5 text-p-sm">
            No backups in this archive.
          </p>
        </div>
      </div>
    </div>
  </Dialog>
</template>
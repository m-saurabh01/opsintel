import {
  BookOpen, ClipboardList, Cpu, Folder, Fuel, Globe, Hammer, Layers, Plane, Radar, Rocket, ScrollText,
  Settings, ShieldCheck, Users, Wrench,
} from 'lucide-react'

const ICONS = {
  folder: Folder, plane: Plane, settings: Settings, wrench: Wrench, hammer: Hammer, 'shield-check': ShieldCheck,
  'book-open': BookOpen, scroll: ScrollText, clipboard: ClipboardList, radar: Radar, rocket: Rocket, users: Users,
  layers: Layers, globe: Globe, cpu: Cpu, fuel: Fuel,
}

export const ICON_NAMES = Object.keys(ICONS)

export function CategoryIcon({ name, size = 20 }) {
  const Icon = ICONS[name] || Folder
  return <Icon size={size} />
}

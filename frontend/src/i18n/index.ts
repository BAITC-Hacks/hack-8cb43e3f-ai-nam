import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'
import kz from './kz'
import ru from './ru'

const saved = (() => {
  try {
    return localStorage.getItem('orgai.lang')
  } catch {
    return null
  }
})()

i18n.use(initReactI18next).init({
  resources: { ru: { translation: ru }, kz: { translation: kz } },
  lng: saved === 'kz' ? 'kz' : 'ru',
  fallbackLng: 'ru',
  interpolation: { escapeValue: false },
})

export const setLang = (lng: 'ru' | 'kz') => {
  i18n.changeLanguage(lng)
  try {
    localStorage.setItem('orgai.lang', lng)
  } catch {
    /* ignore */
  }
}

export default i18n

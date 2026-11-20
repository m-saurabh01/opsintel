export default function PageBanner({ image, icon, title, children }) {
  return (
    <div className="page-banner" style={{ backgroundImage: `linear-gradient(90deg, var(--bg) 18%, rgba(238,243,250,.55) 52%, rgba(238,243,250,0) 78%), url(${image})` }}>
      {icon && <div className="banner-icon">{icon}</div>}
      <div className="banner-text">
        <h1>{title}</h1>
        <p>{children}</p>
      </div>
    </div>
  )
}

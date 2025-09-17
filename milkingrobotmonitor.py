import tkinter as tk
from tkinter import filedialog, ttk, messagebox
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
import seaborn as sns
from datetime import datetime, timedelta
import os
from tkcalendar import DateEntry  # For date picker
import threading
import queue
import time

# Configuratie bestand om styling centraal te beheren
class Config:
    THEME_COLORS = {
        'primary': '#0d3d5c',    # Donkerblauw (hoofdkleur)
        'secondary': '#1b506d',  # Middenblauw
        'light_blue': '#2a7aa1', # Lichtblauw
        'highlight': '#f98d00',  # Oranje (highlight)
        'success': '#27ae60',    # Groen
        'error': '#e74c3c',      # Rood
        'info': '#3498db',       # Informatie blauw
        'white': '#ffffff',      # Wit
        'light_grey': '#f0f2f5', # Lichtgrijs (achtergrond)
        'mid_grey': '#e0e0e0',   # Middengrijs
        'dark_grey': '#555555',  # Donkergrijs (tekst)
    }
    
    STATUS_COLORS = {
        'OK': THEME_COLORS['success'], 
        '!': THEME_COLORS['highlight'], 
        '#': THEME_COLORS['error']
    }
    
    STATUS_LABELS = {
        'OK': 'Geslaagd',
        '!': 'mislukt',
        '#': 'Fout'
    }
    
    DAY_NAMES = ["Maandag", "Dinsdag", "Woensdag", "Donderdag", "Vrijdag", "Zaterdag", "Zondag"]
    
    DAY_NAME_MAP = {
        "Monday": "Maandag", 
        "Tuesday": "Dinsdag", 
        "Wednesday": "Woensdag", 
        "Thursday": "Donderdag", 
        "Friday": "Vrijdag", 
        "Saturday": "Zaterdag", 
        "Sunday": "Zondag"
    }
    
    STAT_PANELS = [
        ("Aantal melkingen", "0", 'highlight'),
        ("Totale melk (L)", "0", 'primary'),
        ("Gem. melk per melking (L)", "0", 'success'),
        ("Gem. melkingen per koe", "0", 'secondary'),
        ("Gem. tijd tussen melkingen (uur)", "0", 'info')
    ]
    
    TABS = {
        "heatmap_melkingen": "Heatmap Melkingen",
        "heatmap_melk": "Heatmap Melk",
        "uur_stats": "Uurstatistieken",
        "dag_stats": "Dagstatistieken",
        "tijd_tussen_melkingen": "Tijd tussen melkingen",
        "totale_melk_per_uur": "Totale melk per uur",
        "trends": "Trends",
        "status": "Status"
    }


# DataProcessor klasse voor alle data-gerelateerde logica
class DataProcessor:
    def __init__(self):
        self.data = None
        self.original_data = None
        self.start_date = None
        self.end_date = None
        self.weeks = []
    
    def load_data(self, file_path):
        """Laad en verwerk data uit een CSV bestand"""
        try:
            # Lees het bestand, sla de eerste regel over (sep=,)
            data = pd.read_csv(file_path, sep=',', skiprows=1, header=None)
            
            # Kolommen benoemen op basis van de beschrijving
            data.columns = ['koe_id', 'levensnummer', 'datum', 'tijd', 'status', 
                           'melk_hoeveelheid', 'frame_nummer', 'fles_nummer', 'kengetal']
            
            # Datum omzetten van DD-MM-YYYY naar datetime
            data['datum'] = pd.to_datetime(data['datum'], format='%d-%m-%Y')
            
            # Combineer datum en tijd
            data['datetime'] = pd.to_datetime(
                data['datum'].dt.strftime('%Y-%m-%d') + ' ' + data['tijd']
            )
            
            # Voeg uur en dag kolommen toe
            data['hour'] = data['datetime'].dt.hour
            data['day'] = data['datetime'].dt.dayofweek
            data['day_name'] = data['datetime'].dt.day_name()
            
            # Voeg week nummer toe (ISO week)
            data['week'] = data['datum'].dt.isocalendar().week
            data['year'] = data['datum'].dt.isocalendar().year
            data['year_week'] = data['year'].astype(str) + '-' + data['week'].astype(str).str.zfill(2)
            
            # Zorg ervoor dat melk_hoeveelheid numeriek is en converteer van milliliters naar liters
            data['melk_hoeveelheid'] = pd.to_numeric(data['melk_hoeveelheid']) / 1000
            
            # Sorteer data op koe_id en datetime voor berekening tijd tussen melkingen
            data = data.sort_values(['koe_id', 'datetime'])
            
            # Bereken tijd tussen melkingen voor dezelfde koe
            data['prev_datetime'] = data.groupby('koe_id')['datetime'].shift(1)
            data['tijd_tussen_melkingen'] = (data['datetime'] - data['prev_datetime']).dt.total_seconds() / 3600  # in uren
            
            # Bepaal unieke weken in de dataset
            self.weeks = sorted(data['year_week'].unique())
            
            # Bepaal min en max datums
            self.start_date = data['datum'].min()
            self.end_date = data['datum'].max()
            
            # Bewaar de originele data
            self.original_data = data.copy()
            self.data = data
            
            return data, None
        except Exception as e:
            return None, str(e)
    
    def filter_data(self, koe_id=None, week=None, start_date=None, end_date=None):
        """Filter data voor een specifieke koe, week of datumreeks indien nodig"""
        if self.original_data is None:
            return None
            
        # Begin met de originele dataset
        filtered_data = self.original_data.copy()
        
        # Filter op koe ID
        if koe_id is not None and koe_id != "Alle koeien":
            koe_id = int(koe_id)
            filtered_data = filtered_data[filtered_data['koe_id'] == koe_id]
        
        # Filter op week
        if week is not None and week != "Alle weken":
            filtered_data = filtered_data[filtered_data['year_week'] == week]
        
        # Filter op datumreeks
        if start_date is not None and end_date is not None:
            filtered_data = filtered_data[(filtered_data['datum'] >= start_date) & 
                                         (filtered_data['datum'] <= end_date)]
        
        # Update de huidige gefilterde data
        self.data = filtered_data
        
        return filtered_data
    
    def get_unique_cows(self):
        """Verkrijg een lijst van alle unieke koe-ID's"""
        if self.data is None:
            return []
        
        return sorted(self.data['koe_id'].unique())
    
    def get_weeks(self):
        """Verkrijg een lijst van alle weken in de data"""
        return self.weeks
    
    def get_date_range(self):
        """Verkrijg de minimum en maximum datum in de data"""
        return self.start_date, self.end_date
    
    def calculate_statistics(self, data):
        """Bereken algemene statistieken van de data"""
        if data is None or len(data) == 0:
            return {
                "total_milkings": 0, 
                "total_milk": 0, 
                "avg_milk": 0, 
                "avg_milkings_per_cow": 0,
                "avg_time_between_milkings": 0
            }
        
        total_milkings = len(data)
        total_milk = data['melk_hoeveelheid'].sum()
        avg_milk = data['melk_hoeveelheid'].mean()
        unique_cows = len(data['koe_id'].unique())
        avg_milkings_per_cow = total_milkings / unique_cows if unique_cows > 0 else 0
        
        # Bereken gemiddelde tijd tussen melkingen (verwijder NaN waarden en uitschieters >24 uur)
        valid_intervals = data['tijd_tussen_melkingen'].dropna()
        valid_intervals = valid_intervals[valid_intervals <= 24]  # Filter onrealistische waarden
        avg_time_between_milkings = valid_intervals.mean() if len(valid_intervals) > 0 else 0
        
        return {
            "total_milkings": total_milkings,
            "total_milk": total_milk,
            "avg_milk": avg_milk,
            "avg_milkings_per_cow": avg_milkings_per_cow,
            "avg_time_between_milkings": avg_time_between_milkings
        }
    
    def calculate_total_milk_per_hour(self, data):
        """Bereken de totale melkhoeveelheid per uur van de dag"""
        if data is None or len(data) == 0:
            return None
        
        hourly_milk = data.groupby('hour')['melk_hoeveelheid'].sum().reset_index()
        return hourly_milk


# VisualizationManager klasse voor alle plot-gerelateerde logica
class VisualizationManager:
    def __init__(self):
        self.current_figures = {}
    
    def create_heatmap_melkingen(self, data):
        """Maak een heatmap voor het aantal melkingen per uur en dag"""
        if len(data) == 0:
            return None
        
        # Maak een nieuwe figuur
        fig, ax = plt.subplots(figsize=(10, 6))
        fig.patch.set_facecolor(Config.THEME_COLORS['light_grey'])
        
        # Maak pivot tabel: aantal per uur en dag
        pivot = pd.crosstab(index=data['day'], columns=data['hour'])
        
        # Maak heatmap
        sns.heatmap(pivot, cmap="YlGnBu", ax=ax, annot=True, fmt="d", linewidths=.5)
        
        # Labels
        ax.set_title("Aantal melkingen per uur en dag", fontsize=14, pad=20)
        ax.set_xlabel("Uur van de dag", fontsize=12, labelpad=10)
        ax.set_ylabel("Dag van de week", fontsize=12, labelpad=10)
        
        # Dag labels aanpassen
        ax.set_yticklabels(Config.DAY_NAMES)
        
        # Adjust layout
        plt.tight_layout()
        
        return fig
    
    def create_heatmap_melk(self, data):
        """Maak een heatmap voor de gemiddelde melkhoeveelheid per uur en dag"""
        if len(data) == 0:
            return None
        
        # Maak een nieuwe figuur
        fig, ax = plt.subplots(figsize=(10, 6))
        fig.patch.set_facecolor(Config.THEME_COLORS['light_grey'])
        
        # Bereken gemiddelde melkhoeveelheid per uur/dag
        milk_pivot = data.pivot_table(
            index='day', 
            columns='hour', 
            values='melk_hoeveelheid',
            aggfunc='mean'
        )
        
        # Maak heatmap
        sns.heatmap(milk_pivot, cmap="BuGn", ax=ax, annot=True, fmt=".1f", linewidths=.5)
        
        # Labels
        ax.set_title("Gemiddelde melkhoeveelheid (L) per uur en dag", fontsize=14, pad=20)
        ax.set_xlabel("Uur van de dag", fontsize=12, labelpad=10)
        ax.set_ylabel("Dag van de week", fontsize=12, labelpad=10)
        
        # Dag labels aanpassen
        ax.set_yticklabels(Config.DAY_NAMES)
        
        # Adjust layout
        plt.tight_layout()
        
        return fig
    
    def create_uur_stats(self, data):
        """Maak grafieken voor uurstatistieken"""
        if len(data) == 0:
            return None
        
        # Maak een nieuwe figuur
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
        fig.patch.set_facecolor(Config.THEME_COLORS['light_grey'])
        
        # Bereken statistieken per uur
        hour_stats = data.groupby('hour').agg({
            'koe_id': 'count',
            'melk_hoeveelheid': 'mean'
        }).reset_index()
        hour_stats.rename(columns={'koe_id': 'count'}, inplace=True)
        
        # Plot aantal melkingen per uur
        ax1.bar(hour_stats['hour'], hour_stats['count'], color=Config.THEME_COLORS['primary'])
        ax1.set_title("Aantal melkingen per uur", fontsize=14, pad=15)
        ax1.set_ylabel("Aantal melkingen", fontsize=12)
        ax1.grid(axis='y', linestyle='--', alpha=0.7)
        
        # Plot gemiddelde melkhoeveelheid per uur
        ax2.plot(hour_stats['hour'], hour_stats['melk_hoeveelheid'], 
                 color=Config.THEME_COLORS['highlight'], 
                 marker='o', linewidth=3, markersize=8)
        ax2.set_title("Gemiddelde melkhoeveelheid (L) per uur", fontsize=14, pad=15)
        ax2.set_xlabel("Uur van de dag", fontsize=12)
        ax2.set_ylabel("Gemiddelde melk (L)", fontsize=12)
        ax2.grid(linestyle='--', alpha=0.7)
        
        # X-as labels
        ax2.set_xticks(range(0, 24))
        
        # Layout aanpassen
        plt.tight_layout()
        
        return fig
    
    def create_dag_stats(self, data):
        """Maak grafieken voor dagstatistieken"""
        if len(data) == 0:
            return None
        
        # Maak een nieuwe figuur
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8), sharex=True)
        fig.patch.set_facecolor(Config.THEME_COLORS['light_grey'])
        
        # Bereken statistieken per dag
        day_stats = data.groupby('day_name').agg({
            'koe_id': 'count',
            'melk_hoeveelheid': 'mean'
        }).reset_index()
        day_stats.rename(columns={'koe_id': 'count'}, inplace=True)
        
        # Zorg voor correcte volgorde van dagen
        day_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        day_stats['day_order'] = day_stats['day_name'].map(lambda x: day_order.index(x))
        day_stats = day_stats.sort_values('day_order')
        
        # Nederlandse dagnamen
        day_stats['nl_day'] = day_stats['day_name'].map(Config.DAY_NAME_MAP)
        
        # Plot aantal melkingen per dag
        ax1.bar(day_stats['nl_day'], day_stats['count'], color=Config.THEME_COLORS['secondary'])
        ax1.set_title("Aantal melkingen per dag", fontsize=14, pad=15)
        ax1.set_ylabel("Aantal melkingen", fontsize=12)
        ax1.grid(axis='y', linestyle='--', alpha=0.7)
        
        # Plot gemiddelde melkhoeveelheid per dag
        ax2.bar(day_stats['nl_day'], day_stats['melk_hoeveelheid'], color=Config.THEME_COLORS['success'])
        ax2.set_title("Gemiddelde melkhoeveelheid (L) per dag", fontsize=14, pad=15)
        ax2.set_xlabel("Dag van de week", fontsize=12)
        ax2.set_ylabel("Gemiddelde melk (L)", fontsize=12)
        ax2.grid(axis='y', linestyle='--', alpha=0.7)
        
        # Layout aanpassen
        plt.tight_layout()
        
        return fig
    
    def create_tijd_tussen_melkingen(self, data):
        """Maak grafieken voor de tijd tussen melkingen"""
        if len(data) == 0:
            return None
        
        # Verwijder NaN en filter onrealistische waarden (>24 uur)
        filtered_data = data.dropna(subset=['tijd_tussen_melkingen'])
        filtered_data = filtered_data[filtered_data['tijd_tussen_melkingen'] <= 24]
        
        if len(filtered_data) == 0:
            return None
        
        # Maak een nieuwe figuur met twee subplots
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
        fig.patch.set_facecolor(Config.THEME_COLORS['light_grey'])
        
        # 1. Histogram van tijd tussen melkingen
        sns.histplot(filtered_data['tijd_tussen_melkingen'], bins=24, kde=True, color=Config.THEME_COLORS['info'], ax=ax1)
        ax1.set_title("Verdeling van tijd tussen melkingen", fontsize=14, pad=15)
        ax1.set_xlabel("Uren tussen melkingen", fontsize=12)
        ax1.set_ylabel("Aantal melkingen", fontsize=12)
        ax1.grid(linestyle='--', alpha=0.7)
        
        # 2. Gemiddelde tijd tussen melkingen per koe (top 15)
        avg_time_per_cow = filtered_data.groupby('koe_id')['tijd_tussen_melkingen'].mean().reset_index()
        avg_time_per_cow = avg_time_per_cow.sort_values('tijd_tussen_melkingen').head(15)
        
        bars = ax2.barh(avg_time_per_cow['koe_id'].astype(str), avg_time_per_cow['tijd_tussen_melkingen'], 
                     color=Config.THEME_COLORS['secondary'])
        ax2.set_title("Gemiddelde tijd tussen melkingen per koe (top 15)", fontsize=14, pad=15)
        ax2.set_xlabel("Gemiddelde tijd (uren)", fontsize=12)
        ax2.set_ylabel("Koe ID", fontsize=12)
        ax2.grid(axis='x', linestyle='--', alpha=0.7)
        
        # Voeg waarden toe aan de staven
        for bar in bars:
            width = bar.get_width()
            label_x_pos = width + 0.1
            ax2.text(label_x_pos, bar.get_y() + bar.get_height()/2, f"{width:.1f}u", 
                    va='center', fontsize=8)
        
        # Layout aanpassen
        plt.tight_layout()
        
        return fig
    
    def create_totale_melk_per_uur(self, data):
        """Maak een grafiek met de totale melkhoeveelheid per uur van de dag"""
        if len(data) == 0:
            return None
        
        # Bereken totale melk per uur
        hourly_milk = data.groupby('hour')['melk_hoeveelheid'].sum().reset_index()
        
        # Maak een nieuwe figuur
        fig, ax = plt.subplots(figsize=(10, 6))
        fig.patch.set_facecolor(Config.THEME_COLORS['light_grey'])
        
        # Staafdiagram met totale melk per uur
        bars = ax.bar(hourly_milk['hour'], hourly_milk['melk_hoeveelheid'], 
                 color=Config.THEME_COLORS['info'])
        
        # Titel en labels
        ax.set_title("Totale melkhoeveelheid per uur van de dag", fontsize=14, pad=20)
        ax.set_xlabel("Uur van de dag", fontsize=12, labelpad=10)
        ax.set_ylabel("Totale melk (L)", fontsize=12, labelpad=10)
        
        # X-as instellingen
        ax.set_xticks(range(0, 24))
        
        # Voeg waarden toe aan de staven
        for bar in bars:
            height = bar.get_height()
            ax.text(bar.get_x() + bar.get_width()/2., height + 5,
                  f'{height:.0f}L', ha='center', va='bottom', fontsize=8)
        
        # Grid
        ax.grid(axis='y', linestyle='--', alpha=0.7)
        
        # Voeg een lijn toe die het cumulatieve percentage toont
        ax2 = ax.twinx()
        hourly_milk['cumulative_percentage'] = hourly_milk['melk_hoeveelheid'].cumsum() / hourly_milk['melk_hoeveelheid'].sum() * 100
        ax2.plot(hourly_milk['hour'], hourly_milk['cumulative_percentage'], 
                color=Config.THEME_COLORS['highlight'], marker='o', linewidth=2)
        ax2.set_ylabel('Cumulatief percentage (%)', color=Config.THEME_COLORS['highlight'], fontsize=12)
        ax2.tick_params(axis='y', labelcolor=Config.THEME_COLORS['highlight'])
        ax2.set_ylim(0, 105)
        
        # Layout aanpassen
        plt.tight_layout()
        
        return fig
    
    def create_trends(self, data):
        """Maak trendgrafieken voor melk en aantal melkingen over tijd"""
        if len(data) == 0:
            return None
        
        # Maak een nieuwe figuur
        fig, ax = plt.subplots(figsize=(10, 6))
        fig.patch.set_facecolor(Config.THEME_COLORS['light_grey'])
        
        # Bereken totale melk per dag
        daily_milk = data.groupby(data['datum'].dt.date).agg({
            'melk_hoeveelheid': 'sum',
            'koe_id': 'count'
        }).reset_index()
        daily_milk.rename(columns={'datum': 'date', 'koe_id': 'count'}, inplace=True)
        
        # Sorteer op datum
        daily_milk = daily_milk.sort_values('date')
        
        # Twin axes voor melk en aantal
        ax2 = ax.twinx()
        
        # Plot totale melk per dag
        line1 = ax.plot(daily_milk['date'], daily_milk['melk_hoeveelheid'], 
                       color=Config.THEME_COLORS['primary'], marker='o', linewidth=3, label='Totale melk (L)')
        ax.set_ylabel('Totale melk (L)', color=Config.THEME_COLORS['primary'], fontsize=12)
        ax.tick_params(axis='y', labelcolor=Config.THEME_COLORS['primary'])
        
        # Plot aantal melkingen per dag
        line2 = ax2.plot(daily_milk['date'], daily_milk['count'], 
                        color=Config.THEME_COLORS['highlight'], marker='x', linewidth=3, label='Aantal melkingen')
        ax2.set_ylabel('Aantal melkingen', color=Config.THEME_COLORS['highlight'], fontsize=12)
        ax2.tick_params(axis='y', labelcolor=Config.THEME_COLORS['highlight'])
        
        # Titel en labels
        ax.set_title("Dagelijkse melkopbrengst en aantal melkingen", fontsize=14, pad=15)
        ax.set_xlabel("Datum", fontsize=12)
        
        # Datumformaat aanpassen
        fig.autofmt_xdate()
        
        # Voeg een gecombineerde legend toe
        lines = line1 + line2
        labels = [l.get_label() for l in lines]
        ax.legend(lines, labels, loc='best')
        
        # Grid
        ax.grid(linestyle='--', alpha=0.7)
        
        # Layout aanpassen
        plt.tight_layout()
        
        return fig
    
    def create_status(self, data):
        """Maak een statusoverzicht"""
        if len(data) == 0:
            return None
        
        # Maak een nieuwe figuur
        fig, ax = plt.subplots(figsize=(10, 6))
        fig.patch.set_facecolor(Config.THEME_COLORS['light_grey'])
        
        # Bereken aantal melkingen per status
        status_counts = data['status'].value_counts()
        
        # Status kleuren gebruiken uit config
        status_colors = [Config.STATUS_COLORS.get(s, Config.THEME_COLORS['dark_grey']) for s in status_counts.index]
        
        # Plot pie chart met een modern donut-stijl
        wedges, texts, autotexts = ax.pie(
            status_counts, 
            labels=status_counts.index,
            autopct='%1.1f%%',
            colors=status_colors,
            startangle=90,
            wedgeprops=dict(width=0.5, edgecolor='white')  # Donut stijl
        )
        
        # Stel eigenschappen in voor de text objecten
        for text in texts:
            text.set_fontsize(12)
        for autotext in autotexts:
            autotext.set_fontsize(12)
            autotext.set_fontweight('bold')
            autotext.set_color('white')
        
        # Titel
        ax.set_title("Verdeling van melkingsstatus", fontsize=14, pad=15)
        
        # Legenda met labels uit config
        legend_labels = [f"{s} - {Config.STATUS_LABELS.get(s, 'Onbekend')}" for s in status_counts.index]
        ax.legend(wedges, legend_labels, loc="center", bbox_to_anchor=(0.5, 0), 
                 ncol=3, fontsize=12, frameon=False)
        
        # Zorg voor een mooie cirkel
        ax.axis('equal')
        
        return fig
    
    def create_week_comparison(self, data):
        """Maak een vergelijking tussen weken"""
        if len(data) == 0:
            return None
        
        # Maak een nieuwe figuur
        fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(10, 8))
        fig.patch.set_facecolor(Config.THEME_COLORS['light_grey'])
        
        # Bereken statistieken per week
        week_stats = data.groupby('year_week').agg({
            'koe_id': 'count',
            'melk_hoeveelheid': 'sum'
        }).reset_index()
        week_stats.rename(columns={'koe_id': 'aantal_melkingen'}, inplace=True)
        
        # Sorteer op weeknummer
        week_stats = week_stats.sort_values('year_week')
        
        # Plot aantal melkingen per week
        ax1.bar(week_stats['year_week'], week_stats['aantal_melkingen'], color=Config.THEME_COLORS['primary'])
        ax1.set_title("Aantal melkingen per week", fontsize=14, pad=15)
        ax1.set_ylabel("Aantal melkingen", fontsize=12)
        ax1.tick_params(axis='x', rotation=45)
        ax1.grid(axis='y', linestyle='--', alpha=0.7)
        
        # Plot totale melkhoeveelheid per week
        ax2.bar(week_stats['year_week'], week_stats['melk_hoeveelheid'], color=Config.THEME_COLORS['highlight'])
        ax2.set_title("Totale melkhoeveelheid (L) per week", fontsize=14, pad=15)
        ax2.set_xlabel("Week", fontsize=12)
        ax2.set_ylabel("Totale melk (L)", fontsize=12)
        ax2.tick_params(axis='x', rotation=45)
        ax2.grid(axis='y', linestyle='--', alpha=0.7)
        
        # Layout aanpassen
        plt.tight_layout()
        
        return fig


# Verbeterde PlotTab klasse
class PlotTab:
    def __init__(self, parent):
        self.frame = ttk.Frame(parent, style='TFrame')
        self.canvas = None
        self.toolbar = None
        self.loading_label = None
        self.is_loading = False
    
    def clear(self):
        # Verwijder alle huidige widgets
        for widget in self.frame.winfo_children():
            widget.destroy()
        
        # Reset canvas en toolbar
        self.canvas = None
        self.toolbar = None
    
    def set_empty_message(self, message="Geen data beschikbaar"):
        self.clear()
        lbl = tk.Label(
            self.frame, 
            text=message,
            bg=Config.THEME_COLORS['light_grey'],
            fg=Config.THEME_COLORS['dark_grey'],
            font=('Segoe UI', 12)
        )
        lbl.pack(expand=True)
    
    def set_loading(self, is_loading=True):
        """Toon of verberg een laadmelding"""
        self.is_loading = is_loading
        
        # Verwijder bestaande laadmelding als die er is
        if self.loading_label:
            self.loading_label.destroy()
            self.loading_label = None
        
        if is_loading:
            # Toon laadmelding
            self.loading_label = tk.Label(
                self.frame, 
                text="Bezig met laden...",
                bg=Config.THEME_COLORS['light_grey'],
                fg=Config.THEME_COLORS['primary'],
                font=('Segoe UI', 12, 'italic')
            )
            self.loading_label.pack(expand=True)
    
    def set_figure(self, figure):
        self.clear()
        
        if figure is None:
            self.set_empty_message()
            return
        
        # Embed in tkinter
        self.canvas = FigureCanvasTkAgg(figure, master=self.frame)
        self.canvas.draw()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Voeg toolbar toe
        self.toolbar = NavigationToolbar2Tk(self.canvas, self.frame)
        self.toolbar.update()
        self.canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)
    
    def get_frame(self):
        return self.frame
    
    def redraw(self):
        if self.canvas:
            self.canvas.draw()


# UI Component classes voor herbruikbaarheid
class StatPanel:
    def __init__(self, parent, title, value, color_key, height=150):
        color = Config.THEME_COLORS[color_key]
        
        # Maak een statistiek card met titel en waarde
        self.frame = tk.Frame(
            parent, 
            bg=Config.THEME_COLORS['white'], 
            height=height,
            highlightbackground=color,
            highlightthickness=1,
            highlightcolor=color,
        )
        
        # Gekleurde header
        header = tk.Frame(self.frame, bg=color, height=30)
        header.pack(fill=tk.X)
        
        header_label = tk.Label(
            header, 
            text=title, 
            fg=Config.THEME_COLORS['white'], 
            bg=color,
            font=('Segoe UI', 10, 'bold'),
            padx=10,
            pady=5
        )
        header_label.pack(anchor=tk.W)
        
        # Value label
        self.value_var = tk.StringVar(value=value)
        value_label = tk.Label(
            self.frame, 
            textvariable=self.value_var, 
            bg=Config.THEME_COLORS['white'],
            fg=color,
            font=('Segoe UI', 36, 'bold'),
            padx=10,
            pady=20
        )
        value_label.pack(fill=tk.BOTH, expand=True)
    
    def set_value(self, value):
        self.value_var.set(value)
    
    def get_frame(self):
        return self.frame


# Nieuwe class voor datum en week selectie
class DateRangeSelector:
    def __init__(self, parent, callback=None):
        self.frame = tk.Frame(parent, bg=Config.THEME_COLORS['light_grey'])
        self.callback = callback
        
        # Week selectie
        self.week_var = tk.StringVar(value="Alle weken")
        self.week_dropdown = None
        
        # Datum selectie
        self.start_date_var = tk.StringVar()
        self.end_date_var = tk.StringVar()
        self.start_date_picker = None
        self.end_date_picker = None
        
        # Filter modus
        self.filter_mode = tk.StringVar(value="week")
        
        # Build UI
        self.setup_ui()
    
    def setup_ui(self):
        # Filter modus selectie
        filter_frame = tk.LabelFrame(
            self.frame, 
            text="Filter modus", 
            bg=Config.THEME_COLORS['light_grey'],
            fg=Config.THEME_COLORS['dark_grey'],
            font=('Segoe UI', 10, 'bold')
        )
        filter_frame.pack(fill=tk.X, pady=5)
        
        # Radio buttons voor filter modus
        tk.Radiobutton(
            filter_frame, 
            text="Per week", 
            variable=self.filter_mode, 
            value="week",
            command=self.toggle_filter_mode,
            bg=Config.THEME_COLORS['light_grey'],
            fg=Config.THEME_COLORS['dark_grey'],
            selectcolor=Config.THEME_COLORS['light_grey']
        ).pack(side=tk.LEFT, padx=10, pady=5)
        
        tk.Radiobutton(
            filter_frame, 
            text="Datumreeks", 
            variable=self.filter_mode, 
            value="date",
            command=self.toggle_filter_mode,
            bg=Config.THEME_COLORS['light_grey'],
            fg=Config.THEME_COLORS['dark_grey'],
            selectcolor=Config.THEME_COLORS['light_grey']
        ).pack(side=tk.LEFT, padx=10, pady=5)
        
        # Week selectie frame
        self.week_frame = tk.Frame(self.frame, bg=Config.THEME_COLORS['light_grey'])
        self.week_frame.pack(fill=tk.X, pady=5)
        
        tk.Label(
            self.week_frame, 
            text="Selecteer week:", 
            bg=Config.THEME_COLORS['light_grey'],
            fg=Config.THEME_COLORS['dark_grey']
        ).pack(side=tk.LEFT, padx=(0, 5))
        
        self.week_dropdown = ttk.Combobox(
            self.week_frame,
            textvariable=self.week_var,
            state="readonly",
            width=15
        )
        self.week_dropdown.pack(side=tk.LEFT, padx=5)
        self.week_dropdown.bind("<<ComboboxSelected>>", self.on_filter_change)
        
        # Datum selectie frame
        self.date_frame = tk.Frame(self.frame, bg=Config.THEME_COLORS['light_grey'])
        
        # Van datum
        tk.Label(
            self.date_frame, 
            text="Van:", 
            bg=Config.THEME_COLORS['light_grey'],
            fg=Config.THEME_COLORS['dark_grey']
        ).pack(side=tk.LEFT, padx=(0, 5))
        
        self.start_date_picker = DateEntry(
            self.date_frame, 
            width=12, 
            background=Config.THEME_COLORS['primary'],
            foreground=Config.THEME_COLORS['white'],
            borderwidth=2,
            date_pattern='dd-mm-yyyy',
            textvariable=self.start_date_var
        )
        self.start_date_picker.pack(side=tk.LEFT, padx=5)
        self.start_date_picker.bind("<<DateEntrySelected>>", self.on_filter_change)
        
        # Tot datum
        tk.Label(
            self.date_frame, 
            text="Tot:", 
            bg=Config.THEME_COLORS['light_grey'],
            fg=Config.THEME_COLORS['dark_grey']
        ).pack(side=tk.LEFT, padx=(10, 5))
        
        self.end_date_picker = DateEntry(
            self.date_frame, 
            width=12, 
            background=Config.THEME_COLORS['primary'],
            foreground=Config.THEME_COLORS['white'],
            borderwidth=2,
            date_pattern='dd-mm-yyyy',
            textvariable=self.end_date_var
        )
        self.end_date_picker.pack(side=tk.LEFT, padx=5)
        self.end_date_picker.bind("<<DateEntrySelected>>", self.on_filter_change)
        
        # Toon alleen het actieve frame
        self.toggle_filter_mode()
    
    def toggle_filter_mode(self):
        # Verberg beide frames eerst
        self.week_frame.pack_forget()
        self.date_frame.pack_forget()
        
        # Toon het juiste frame gebaseerd op de modus
        if self.filter_mode.get() == "week":
            self.week_frame.pack(fill=tk.X, pady=5)
        else:
            self.date_frame.pack(fill=tk.X, pady=5)
    
    def on_filter_change(self, event=None):
        if self.callback:
            self.callback()
    
    def set_weeks(self, weeks):
        """Update de beschikbare weken in de dropdown"""
        if not weeks:
            return
        
        weeks_list = ["Alle weken"] + list(weeks)
        self.week_dropdown['values'] = weeks_list
        
        # Reset naar 'Alle weken'
        self.week_var.set("Alle weken")
    
    def set_date_range(self, start_date, end_date):
        """Update de min/max datums voor de date pickers"""
        if start_date and end_date:
            # Format voor DateEntry is datetime object
            self.start_date_picker.set_date(start_date)
            self.end_date_picker.set_date(end_date)
    
    def get_selected_filter(self):
        """Krijg de geselecteerde filter waarden"""
        if self.filter_mode.get() == "week":
            return {
                "mode": "week",
                "week": self.week_var.get()
            }
        else:
            try:
                start_date = datetime.strptime(self.start_date_var.get(), '%d-%m-%Y').date()
                end_date = datetime.strptime(self.end_date_var.get(), '%d-%m-%Y').date()
                return {
                    "mode": "date",
                    "start_date": pd.Timestamp(start_date),
                    "end_date": pd.Timestamp(end_date)
                }
            except Exception as e:
                return {
                    "mode": "date",
                    "start_date": None,
                    "end_date": None
                }
    
    def get_frame(self):
        return self.frame


# Hoofdapplicatie klasse
class MelkrobotDashboard:
    def __init__(self, root):
        self.root = root
        self.root.title("MelkMonitor")
        self.root.geometry("1280x800")
        self.root.configure(bg=Config.THEME_COLORS['light_grey'])
        
        # Initialiseer managers
        self.data_processor = DataProcessor()
        self.viz_manager = VisualizationManager()
        
        # Tabs en stat panels
        self.tabs = {}
        self.stat_panels = []
        
        # Status en koe selectie
        self.status_var = tk.StringVar(value="Geen data geladen")
        self.koe_var = tk.StringVar(value="Alle koeien")
        
        # Datum range selector
        self.date_range_selector = None
        
        # Threading componenten toevoegen
        self.plot_queue = queue.Queue()
        self.worker_thread = None
        self.is_updating = False
        self.progress_var = tk.DoubleVar(value=0)
        self.progress_bar = None
        
        # GUI opbouwen
        self.setup_ui()
        
        # Periodieke controle voor thread resultaten
        self.check_queue()
    
    def check_queue(self):
        try:
            # Controleer of er items in de queue staan
            while not self.plot_queue.empty():
                item = self.plot_queue.get_nowait()
                # Verwerk het resultaat
                if item:
                    tab_name, fig = item
                    
                    # Sla figuur op voor export
                    if fig is not None:
                        self.viz_manager.current_figures[tab_name] = fig
                    
                    # Wijs figuur toe aan de juiste tab
                    if tab_name in self.tabs:
                        self.tabs[tab_name].set_figure(fig)
                    
                    # Update progressbar
                    self.progress_var.set(self.progress_var.get() + 1)
                
                # Markeer taak als voltooid
                self.plot_queue.task_done()
            
            # Controleer of alle updates zijn voltooid
            if self.is_updating and self.worker_thread and not self.worker_thread.is_alive() and self.plot_queue.empty():
                self.complete_update()
        except Exception as e:
            # Log error
            print(f"Error in check_queue: {str(e)}")
        finally:
            # Plan de volgende check
            self.root.after(100, self.check_queue)
    
    def complete_update(self):
        self.is_updating = False
        if self.progress_bar:
            self.progress_bar.pack_forget()  # Verberg progressbar
        self.status_var.set("Update voltooid")
        # Enable UI controls
        self.toggle_ui_controls(True)
    
    def toggle_ui_controls(self, enable):
        state = 'normal' if enable else 'disabled'
        # Update dropdown status
        if hasattr(self, 'koe_dropdown') and self.koe_dropdown['state'] != 'disabled':
            self.koe_dropdown['state'] = 'readonly' if enable else 'disabled'
        
        # Disable/enable date selectors
        if hasattr(self, 'date_range_selector'):
            if hasattr(self.date_range_selector, 'week_dropdown'):
                self.date_range_selector.week_dropdown['state'] = 'readonly' if enable else 'disabled'
            if hasattr(self.date_range_selector, 'start_date_picker'):
                self.date_range_selector.start_date_picker['state'] = state
            if hasattr(self.date_range_selector, 'end_date_picker'):
                self.date_range_selector.end_date_picker['state'] = state
    
    def setup_ui(self):
        # Configureer stijlen
        self.configure_styles()
        
        # Maak menu
        self.create_menu()
        
        # Hoofdcontainer met padding
        main_container = tk.Frame(self.root, bg=Config.THEME_COLORS['light_grey'], padx=15, pady=15)
        main_container.pack(fill=tk.BOTH, expand=True)
        
        # Header frame
        self.create_header(main_container)
        
        # Progress bar container toevoegen
        progress_frame = tk.Frame(main_container, bg=Config.THEME_COLORS['light_grey'])
        progress_frame.pack(fill=tk.X, pady=(0, 5))
        
        self.progress_bar = ttk.Progressbar(
            progress_frame,
            variable=self.progress_var,
            maximum=len(Config.TABS) + 1,  # +1 voor week_comparison
            length=200,
            mode='determinate'
        )
        # Verberg de progressbar initieel
        self.progress_bar.pack(fill=tk.X, padx=10, pady=5)
        self.progress_bar.pack_forget()  # Verberg totdat nodig
        
        # Datum/week filter sectie
        filter_section = tk.Frame(main_container, bg=Config.THEME_COLORS['light_grey'], padx=10, pady=10)
        filter_section.pack(fill=tk.X, pady=(0, 10))
        
        # Voeg datum range selector toe
        self.date_range_selector = DateRangeSelector(filter_section, callback=self.update_plots)
        self.date_range_selector.get_frame().pack(fill=tk.X)
        
        # Dashboard content in twee kolommen
        content_frame = tk.Frame(main_container, bg=Config.THEME_COLORS['light_grey'])
        content_frame.pack(fill=tk.BOTH, expand=True)
        
        # Linker kolom (70% breedte) - Hoofdgrafieken
        left_column = tk.Frame(content_frame, bg=Config.THEME_COLORS['light_grey'])
        left_column.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        
        # Rechter kolom (30% breedte) - Overzicht en kleine grafieken
        right_column = tk.Frame(content_frame, bg=Config.THEME_COLORS['light_grey'], width=300)
        right_column.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(10, 0))
        right_column.pack_propagate(False)  # Zorgt ervoor dat de breedte van 300 behouden blijft
        
        # Maak tabbladen in de linker kolom
        self.notebook = ttk.Notebook(left_column, style='TNotebook')
        self.notebook.pack(fill=tk.BOTH, expand=True)
        
        # Tabbladen maken
        self.create_tabs()
        
        # Maak stat panels in de rechter kolom
        self.create_stat_panels(right_column)
        
        # Status bar onderaan
        self.create_status_bar()
    
    def configure_styles(self):
        # Configureer ttk stijlen
        style = ttk.Style()
        
        # Algemene stijl
        style.configure('TFrame', background=Config.THEME_COLORS['light_grey'])
        style.configure('TLabel', background=Config.THEME_COLORS['light_grey'], foreground=Config.THEME_COLORS['dark_grey'])
        style.configure('TNotebook', background=Config.THEME_COLORS['light_grey'], tabmargins=[2, 5, 2, 0])
        style.configure('TNotebook.Tab', background=Config.THEME_COLORS['light_grey'], padding=[15, 5], font=('Segoe UI', 10))
        style.map('TNotebook.Tab', 
                 background=[('selected', Config.THEME_COLORS['primary'])],
                 foreground=[('selected', Config.THEME_COLORS['white'])])
        
        # Buttons
        style.configure('TButton', font=('Segoe UI', 10), padding=6)
        style.configure('Primary.TButton', background=Config.THEME_COLORS['primary'], foreground=Config.THEME_COLORS['white'])
        style.map('Primary.TButton',
                 background=[('active', Config.THEME_COLORS['secondary'])],
                 foreground=[('active', Config.THEME_COLORS['white'])])
        
        # Combobox
        style.configure('TCombobox', foreground=Config.THEME_COLORS['dark_grey'], padding=5)
    
    def create_menu(self):
        menubar = tk.Menu(self.root)
        
        # Bestand menu
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open", command=self.open_file)
        file_menu.add_separator()
        file_menu.add_command(label="Exporteer huidige visualisatie", command=self.export_current)
        file_menu.add_command(label="Exporteer alles als PDF", command=self.export_pdf)
        file_menu.add_separator()
        file_menu.add_command(label="Afsluiten", command=self.root.destroy)
        menubar.add_cascade(label="Bestand", menu=file_menu)
        
        # Weergave menu
        view_menu = tk.Menu(menubar, tearoff=0)
        view_menu.add_command(label="Reset zoom", command=self.reset_zoom)
        menubar.add_cascade(label="Weergave", menu=view_menu)
        
        # Help menu
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Over", command=self.show_about)
        menubar.add_cascade(label="Help", menu=help_menu)
        
        self.root.config(menu=menubar)
    
    def create_header(self, parent):
        header_frame = tk.Frame(parent, bg=Config.THEME_COLORS['light_grey'])
        header_frame.pack(fill=tk.X, pady=(0, 15))
        
        # Logo en titel
        title_frame = tk.Frame(header_frame, bg=Config.THEME_COLORS['light_grey'])
        title_frame.pack(side=tk.LEFT, fill=tk.Y)
        
        title_label = tk.Label(
            title_frame, 
            text="MelkMonitor - gemaakt door Jacob's Farm", 
            font=('Segoe UI', 18, 'bold'), 
            fg=Config.THEME_COLORS['primary'],
            bg=Config.THEME_COLORS['light_grey']
        )
        title_label.pack(side=tk.LEFT, padx=5)
        
        # Knop om bestand te openen
        open_button = ttk.Button(
            header_frame, 
            text="Open Bestand", 
            command=self.open_file,
            style='Primary.TButton'
        )
        open_button.pack(side=tk.RIGHT, padx=5)
        
        # Koe selectie
        tk.Label(
            header_frame, 
            text="Selecteer koe:", 
            bg=Config.THEME_COLORS['light_grey'],
            fg=Config.THEME_COLORS['dark_grey']
        ).pack(side=tk.RIGHT, padx=(20, 5))
        
        self.koe_dropdown = ttk.Combobox(
            header_frame, 
            textvariable=self.koe_var, 
            state="disabled",
            width=20,
            style='TCombobox'
        )
        self.koe_dropdown.pack(side=tk.RIGHT)
        self.koe_dropdown.bind("<<ComboboxSelected>>", self.update_plots)
    
    def create_tabs(self):
        # Maak een plot tab voor elke gewenste visualisatie
        tabs_config = {**Config.TABS, "week_comparison": "Week Vergelijking"}
        
        for key, title in tabs_config.items():
            tab = PlotTab(self.notebook)
            self.tabs[key] = tab
            self.notebook.add(tab.get_frame(), text=title)
        
        # Bind tab change event
        self.notebook.bind("<<NotebookTabChanged>>", self.on_tab_changed)
    
    def on_tab_changed(self, event):
        """Wordt aangeroepen wanneer de gebruiker van tab wisselt"""
        # Haal de nieuwe actieve tab op
        try:
            current_tab_idx = self.notebook.index(self.notebook.select())
            tab_names = list(self.tabs.keys())
            active_tab = tab_names[current_tab_idx] if current_tab_idx < len(tab_names) else None
            
            # Controleer of deze tab een canvas heeft
            if active_tab and active_tab in self.tabs:
                tab = self.tabs[active_tab]
                # Herlaad canvas indien nodig
                if tab.canvas:
                    tab.redraw()
        except Exception as e:
            print(f"Error in on_tab_changed: {str(e)}")
    
    def create_stat_panels(self, parent):
        # Maak stat panels op basis van configuratie
        panel_margin = 10
        
        for i, (title, value, color_key) in enumerate(Config.STAT_PANELS):
            panel = StatPanel(parent, title, value, color_key)
            panel.get_frame().pack(fill=tk.X, pady=(0, panel_margin))
            self.stat_panels.append(panel)
    
    def create_status_bar(self):
        # Status bar onderaan
        status_frame = tk.Frame(self.root, bg=Config.THEME_COLORS['primary'], height=28)
        status_frame.pack(side=tk.BOTTOM, fill=tk.X)
        status_label = tk.Label(
            status_frame, 
            textvariable=self.status_var, 
            bg=Config.THEME_COLORS['primary'],
            fg=Config.THEME_COLORS['white'],
            anchor=tk.W,
            padx=15,
            pady=4,
            font=('Segoe UI', 9)
        )
        status_label.pack(fill=tk.X)
    
    def open_file(self):
        # Bestand dialoog openen
        file_path = filedialog.askopenfilename(
            title="Open melkrobot databestand",
            filetypes=[("Text bestanden", "*.txt"), ("CSV bestanden", "*.csv"), ("Alle bestanden", "*.*")]
        )
        
        if not file_path:
            return
            
        # Laad data met de DataProcessor
        data, error = self.data_processor.load_data(file_path)
        
        if error:
            messagebox.showerror("Fout bij openen bestand", error)
            return
        
        # Update koe dropdown
        koeien = self.data_processor.get_unique_cows()
        self.koe_dropdown['values'] = ["Alle koeien"] + [str(k) for k in koeien]
        self.koe_dropdown['state'] = 'readonly'
        
        # Update week selector
        weeks = self.data_processor.get_weeks()
        self.date_range_selector.set_weeks(weeks)
        
        # Update date range selector
        start_date, end_date = self.data_processor.get_date_range()
        self.date_range_selector.set_date_range(start_date, end_date)
        
        # Update status
        self.status_var.set(f"Data geladen: {len(data)} rijen van {len(koeien)} koeien, van {start_date.strftime('%d-%m-%Y')} tot {end_date.strftime('%d-%m-%Y')}")
        
        # Update plots
        self.update_plots()
    
    def update_plots(self, event=None):
        # Verkrijg filter instellingen
        koe_id = self.koe_var.get()
        filter_settings = self.date_range_selector.get_selected_filter()
        
        # Filter data op basis van koe en week/datum
        if filter_settings["mode"] == "week":
            week = filter_settings["week"]
            filtered_data = self.data_processor.filter_data(
                koe_id=koe_id,
                week=week if week != "Alle weken" else None
            )
        else:
            # Datum filter
            start_date = filter_settings.get("start_date")
            end_date = filter_settings.get("end_date")
            
            filtered_data = self.data_processor.filter_data(
                koe_id=koe_id,
                start_date=start_date,
                end_date=end_date
            )
        
        if filtered_data is None or len(filtered_data) == 0:
            messagebox.showinfo("Info", "Geen gegevens gevonden voor de geselecteerde filters.")
            return
        
        # Update statistiek kaarten - dit is snel en kan in de hoofdthread
        self.update_stat_panels(filtered_data)
        
        # Start threaded update voor alle plots
        self.start_threaded_update(filtered_data)
    
    def update_stat_panels(self, data):
        # Bereken statistieken
        stats = self.data_processor.calculate_statistics(data)
        
        # Update stat panels
        self.stat_panels[0].set_value(f"{stats['total_milkings']}")
        self.stat_panels[1].set_value(f"{stats['total_milk']:.1f}")
        self.stat_panels[2].set_value(f"{stats['avg_milk']:.1f}")
        self.stat_panels[3].set_value(f"{stats['avg_milkings_per_cow']:.1f}")
        self.stat_panels[4].set_value(f"{stats['avg_time_between_milkings']:.1f}")
    
    def start_threaded_update(self, data):
        # Controleer of er al een update bezig is
        if self.is_updating:
            return
        
        self.is_updating = True
        
        # Reset en toon de progress bar
        self.progress_var.set(0)
        self.progress_bar.pack(fill=tk.X, padx=10, pady=5)
        
        # Disable UI controls
        self.toggle_ui_controls(False)
        
        # Update status
        self.status_var.set("Bezig met bijwerken van grafieken...")
        
        # Start worker thread
        self.worker_thread = threading.Thread(
            target=self.threaded_update_all_tabs,
            args=(data,),
            daemon=True
        )
        self.worker_thread.start()
    
    def threaded_update_all_tabs(self, data):
        try:
            # Bepaal welke tab momenteel actief is
            try:
                current_tab_idx = self.notebook.index(self.notebook.select())
                tab_names = list(self.tabs.keys())
                active_tab = tab_names[current_tab_idx] if current_tab_idx < len(tab_names) else None
            except Exception:
                active_tab = None
            
            # Toon laadmelding in alle tabs
            for tab_name, tab in self.tabs.items():
                # Gebruik de root.after methode om veilig de UI vanuit een thread bij te werken
                self.root.after(0, lambda t=tab: t.set_loading(True))
            
            # Update methodes met prioriteit voor de actieve tab
            update_methods = {
                "heatmap_melkingen": self.viz_manager.create_heatmap_melkingen,
                "heatmap_melk": self.viz_manager.create_heatmap_melk,
                "uur_stats": self.viz_manager.create_uur_stats,
                "dag_stats": self.viz_manager.create_dag_stats,
                "tijd_tussen_melkingen": self.viz_manager.create_tijd_tussen_melkingen,
                "totale_melk_per_uur": self.viz_manager.create_totale_melk_per_uur,
                "trends": self.viz_manager.create_trends,
                "status": self.viz_manager.create_status,
                "week_comparison": self.viz_manager.create_week_comparison
            }
            
            # Prioriteitslijst maken met actieve tab eerst
            tab_order = []
            if active_tab:
                tab_order.append(active_tab)
            
            # Voeg de rest van de tabs toe in de volgorde waarin ze waarschijnlijk gebruikt worden
            important_tabs = ["trends", "heatmap_melkingen", "heatmap_melk"]
            for tab in important_tabs:
                if tab != active_tab and tab in update_methods:
                    tab_order.append(tab)
            
            # Voeg de overige tabs toe
            for tab in update_methods.keys():
                if tab not in tab_order:
                    tab_order.append(tab)
            
            # Verwerk de tabs volgens de prioriteitsvolgorde
            for tab_name in tab_order:
                if tab_name in update_methods:
                    # Maak de figuur in de thread
                    start_time = time.time()
                    
                    fig = update_methods[tab_name](data)
                    
                    # Houd de voortgang bij
                    self.root.after(0, lambda v=self.progress_var.get() + 1: self.progress_var.set(v))
                    
                    # Voeg resultaat toe aan de queue voor de main thread
                    self.plot_queue.put((tab_name, fig))
                    
                    # Log tijdsduur voor deze grafiek (debugging)
                    duration = time.time() - start_time
                    print(f"Tab {tab_name} update duurde {duration:.2f} seconden")
                    
                    # Korte pauze tussen zware taken om CPU te ontlasten
                    time.sleep(0.05)
        
        except Exception as e:
            # Log error en stuur naar queue
            print(f"Error in threaded update: {str(e)}")
            import traceback
            traceback.print_exc()
            self.plot_queue.put(None)
            
            # Update UI naar foutmelding
            self.root.after(0, lambda: self.status_var.set(f"Fout bij bijwerken: {str(e)}"))
    
    def reset_zoom(self):
        # Reset zoom op huidige visualisatie
        current_tab_idx = self.notebook.index(self.notebook.select())
        tab_names = list(self.tabs.keys())
        if current_tab_idx < len(tab_names):
            tab_name = tab_names[current_tab_idx]
            if tab_name in self.tabs:
                self.tabs[tab_name].redraw()
    
    def export_current(self):
        # Exporteer huidige visualisatie als afbeelding
        current_tab_idx = self.notebook.index(self.notebook.select())
        tab_names = list(self.tabs.keys())
        if current_tab_idx < len(tab_names):
            tab_name = tab_names[current_tab_idx]
            tab_title = Config.TABS.get(tab_name, "Visualisatie")
            
            file_path = filedialog.asksaveasfilename(
                title=f"Exporteer {tab_title}",
                defaultextension=".png",
                filetypes=[("PNG", "*.png"), ("JPEG", "*.jpg"), ("PDF", "*.pdf")]
            )
            
            if not file_path:
                return
            
            # Gebruik opgeslagen figuur indien beschikbaar
            if tab_name in self.viz_manager.current_figures:
                figure = self.viz_manager.current_figures[tab_name]
                try:
                    # Zorg ervoor dat het pad correct is
                    file_path = os.path.normpath(file_path)
                    # Save figure
                    figure.savefig(file_path, dpi=300, bbox_inches='tight')
                    messagebox.showinfo("Export", f"Geëxporteerd als {file_path}")
                    
                    # Open het bestand
                    self.open_exported_file(file_path)
                    return
                except Exception as e:
                    messagebox.showerror("Export fout", f"Fout bij opslaan: {str(e)}")
                    return
            
            messagebox.showerror("Export fout", "Geen visualisatie gevonden om te exporteren")
    
    def export_pdf(self):
        # Exporteer alle visualisaties als één PDF
        file_path = filedialog.asksaveasfilename(
            title="Exporteer alle visualisaties als PDF",
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")]
        )
        
        if not file_path:
            return
            
        try:
            from matplotlib.backends.backend_pdf import PdfPages
            # Normaliseer het pad
            file_path = os.path.normpath(file_path)
            
            # Gebruik rechtstreeks de opgeslagen figuren
            with PdfPages(file_path) as pdf:
                # Check of we figuren hebben opgeslagen
                if len(self.viz_manager.current_figures) > 0:
                    for tab_name, figure in self.viz_manager.current_figures.items():
                        pdf.savefig(figure)
                    
                    messagebox.showinfo("Export", f"PDF geëxporteerd als {file_path}")
                    
                    # Open het bestand
                    self.open_exported_file(file_path)
                    return
                
                messagebox.showerror("Export fout", "Geen visualisaties gevonden om te exporteren")
        
        except Exception as e:
            messagebox.showerror("Export fout", str(e))
    
    def open_exported_file(self, file_path):
        """Open een geëxporteerd bestand met het standaard systeem programma"""
        try:
            import platform
            if platform.system() == 'Windows':
                os.startfile(file_path)
            elif platform.system() == 'Darwin':  # macOS
                import subprocess
                subprocess.call(('open', file_path))
            else:  # Linux
                import subprocess
                subprocess.call(('xdg-open', file_path))
        except Exception as e:
            messagebox.showinfo("Info", f"Bestand opgeslagen als {file_path}, maar kon niet automatisch worden geopend.")
    
    def show_about(self):
        messagebox.showinfo(
            "Over MelkMonitor",
            "Versie 4.0\n\n"
            "Deze tool helpt bij het visualiseren van melkrobot-gegevens.\n"
            "Upload een komma-gescheiden tekstbestand met melkgegevens.\n\n"
            "Nieuwe functionaliteit:\n"
            "- Week selectie\n"
            "- Datumbereik selectie\n"
            "- Week vergelijkingen\n"
            "- Multi-threading voor verbeterde responsiviteit"
        )


# Extensie klasse voor uitbreidingen
class ExtendedVisualizationManager(VisualizationManager):
    """Subklasse die extra visualisaties kan toevoegen"""
    
    def create_boxplot_melk(self, data):
        """Maak een boxplot voor melkhoeveelheid per dag"""
        if len(data) == 0:
            return None
        
        # Maak een nieuwe figuur
        fig, ax = plt.subplots(figsize=(10, 6))
        fig.patch.set_facecolor(Config.THEME_COLORS['light_grey'])
        
        # Map dag nummer naar Nederlandse dagnaam
        data['nl_day'] = data['day'].map(lambda x: Config.DAY_NAMES[x])
        
        # Maak boxplot
        sns.boxplot(x='nl_day', y='melk_hoeveelheid', data=data, 
                   ax=ax, palette='Blues')
        
        # Labels
        ax.set_title("Spreiding van melkhoeveelheid per dag", fontsize=14, pad=20)
        ax.set_xlabel("Dag van de week", fontsize=12, labelpad=10)
        ax.set_ylabel("Melkhoeveelheid (L)", fontsize=12, labelpad=10)
        
        # Grid
        ax.grid(axis='y', linestyle='--', alpha=0.7)
        
        # Layout aanpassen
        plt.tight_layout()
        
        return fig


# Start de applicatie
if __name__ == "__main__":
    root = tk.Tk()
    app = MelkrobotDashboard(root)
    root.mainloop()
